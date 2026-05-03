from pupa.scrape import Scraper, Person, Organization
import requests
from lxml import html as lxml_html
import re
import logging

logger = logging.getLogger(__name__)


# seattle.gov serves per-member profiles at
# `/council/members/<lowercase-hyphenated-name>`. The slug is derived
# from the member's display name except when seattle.gov uses a preferred
# name on the URL — keep this dict in sync with the live site.
PROFILE_SLUG_OVERRIDES = {
    "Robert Kettle": "bob-kettle",
}


def profile_slug(name: str) -> str:
    """Slug for the per-member seattle.gov profile page."""
    if name in PROFILE_SLUG_OVERRIDES:
        return PROFILE_SLUG_OVERRIDES[name]
    return name.strip().lower().replace(" ", "-")


def _clean_address(div) -> str:
    """Pull the address out of a `.contactTilePhysicalAddress` /
    `.contactTileMailingAddress` div, preserving the per-line structure
    by treating each `<br/>` as a line break. Skips the `<strong>` label
    ('Street Address:' / 'Mailing Address:') and the close `<button>`.
    Inline whitespace within each line is collapsed; lines are joined
    with `\\n` so the API can store them as a single string and the
    frontend can render via `white-space: pre-line` (or `.split('\\n')`).
    """
    lines: list[str] = []
    buf: list[str] = []

    def flush():
        line = " ".join(" ".join(buf).split())
        if line:
            lines.append(line)
        buf.clear()

    def walk(el):
        if el.tag == "br":
            flush()
        elif el.tag in ("strong", "button"):
            pass  # skip the label and the close-icon button entirely
        else:
            if el.text:
                buf.append(el.text)
            for child in el:
                walk(child)
        if el.tail:
            buf.append(el.tail)

    for child in div:
        walk(child)
    flush()
    return "\n".join(lines)


_COMMITTEE_HREF_PREFIX = "/council/meetings/committees-and-agendas/"
_COMMITTEE_LINE_RE = re.compile(r"^\s*(Chair|Vice-Chair|Vice Chair|Member)\s*:\s*(.+?)\s*$")


def extract_committee_assignments(html_str: str) -> list[dict]:
    """Parse a councilmember's `/committees-and-calendar` page. Returns
    a list of `{role, name, slug, url}` dicts, one per committee.

    Page structure: an `<h2>Committees</h2>` followed by a `<ul>` whose
    `<li>` items each look like

        <li><strong>Chair: <a href="…/<slug>">Committee Name</a></strong></li>

    Three roles observed in the wild: `Chair`, `Vice-Chair`, `Member`.
    The committee `<a>` href is the stable identifier — committee
    *names* on seattle.gov vary in punctuation across reps' pages
    (e.g. `Seattle Center` vs `Seattle-Center`), and we observed at
    least one href/text mismatch (a copy-paste error on rinck's page),
    so callers should dedupe by `slug` and pick a canonical name."""
    h = lxml_html.fromstring(html_str)
    headings = h.xpath('//h2[normalize-space(text())="Committees"]')
    if not headings:
        return []
    ul = headings[0].getparent().xpath('.//ul[1]')
    if not ul:
        return []
    out: list[dict] = []
    for li in ul[0].xpath("./li"):
        text = li.text_content().strip()
        m = _COMMITTEE_LINE_RE.match(text)
        if not m:
            continue
        role_raw, name = m.group(1), m.group(2).strip()
        # Canonicalize 'Vice Chair' → 'Vice-Chair'
        role = "Vice-Chair" if role_raw in ("Vice-Chair", "Vice Chair") else role_raw
        a = li.xpath(".//a")
        if not a:
            continue
        href = a[0].get("href") or ""
        if not href.startswith(_COMMITTEE_HREF_PREFIX):
            continue
        slug = href[len(_COMMITTEE_HREF_PREFIX):].rstrip("/")
        out.append({
            "role": role,
            "name": name,
            "slug": slug,
            "url": "https://www.seattle.gov" + href,
        })
    return out


_PHOTO_PATH_RE = re.compile(r"images/Council/Members/CouncilmemberBanners/[^\"'?]+")


def extract_staff(html_str: str) -> list[dict]:
    """Parse a councilmember's `/staff` page. Returns a list of
    `{name, title, email}` dicts, one per staff member. Bio prose is
    intentionally skipped — the rep page renders staff as a compact
    contact list, not biographical content.

    Page structure: each staff member is a `.boardMemberContent` div
    containing `<h2 class="boardMemberName">`, `<div
    class="boardMemberProfTitle">`, and a `<div class="memberBio">`
    whose first link is the staff member's mailto. We sidebar
    "City Council" / "Citywide Information" headings — those are
    page-chrome, not staff."""
    h = lxml_html.fromstring(html_str)
    out: list[dict] = []
    for block in h.xpath('//div[contains(@class, "boardMemberContent")]'):
        name_nodes = block.xpath('.//h2[@class="boardMemberName"]/text()')
        title_nodes = block.xpath('.//div[@class="boardMemberProfTitle"]/text()')
        email_hrefs = block.xpath('.//div[@class="memberBio"]//a[starts-with(@href, "mailto:")]/@href')
        if not name_nodes:
            continue
        name = name_nodes[0].strip()
        title = title_nodes[0].strip() if title_nodes else ""
        email = email_hrefs[0][len("mailto:"):].strip() if email_hrefs else ""
        out.append({"name": name, "title": title, "email": email})
    return out


def extract_photo_url(html_str: str) -> str | None:
    """Return the absolute URL of the rep's banner photo, if any.

    The seattle.gov main per-member page emits the banner with a
    relative src like `images//images/Council/Members/CouncilmemberBanners/foster_635x250.jpg`
    (the double-slash is a CMS artifact and the server tolerates it,
    but we normalize to the canonical single-slash absolute URL).
    Returns None if the page lacks a banner img — callers leave
    `person.image` unset in that case."""
    m = _PHOTO_PATH_RE.search(html_str)
    if not m:
        return None
    return "https://www.seattle.gov/" + m.group(0)


def extract_contact_details(html_str: str) -> dict:
    """Parse the Contact Us tile on a per-member seattle.gov profile
    page. Returns a dict with any of `phone`, `fax`, `email`,
    `office_address`, `mailing_address`. Missing keys mean the field
    wasn't found — caller decides whether that's a hard error.

    The Contact Us block is rendered server-side as a div with class
    `ContactComponent`; child tiles use stable class names
    (`contactTilePhone`, `contactTileEmail`, `fax`,
    `contactTilePhysicalAddress`, `contactTileMailingAddress`). The two
    address divs' element IDs are misnamed on the live page (the office
    address sits inside `tileMailing_*` and vice-versa) so we key off
    the class name, not the ID."""
    h = lxml_html.fromstring(html_str)
    boxes = h.xpath('//div[contains(@class, "ContactComponent")]')
    if not boxes:
        return {}
    box = boxes[0]
    out: dict[str, str] = {}

    phone = box.xpath('.//div[@class="contactTilePhone"]/a/text()')
    if phone:
        out["phone"] = phone[0].strip()
    fax = box.xpath('.//div[@class="fax"]/a/text()')
    if fax:
        out["fax"] = fax[0].strip()
    email = box.xpath('.//div[@class="contactTileEmail"]/a/text()')
    if email:
        out["email"] = email[0].strip()

    office = box.xpath('.//div[contains(@class, "contactTilePhysicalAddress")]')
    if office:
        out["office_address"] = _clean_address(office[0])
    mailing = box.xpath('.//div[contains(@class, "contactTileMailingAddress")]')
    if mailing:
        out["mailing_address"] = _clean_address(mailing[0])

    return out


class SeattlePersonScraper(Scraper):

    def _fetch_member_extras(self, profile_url: str) -> tuple[dict, list[dict], str | None, list[dict]]:
        """Fetch the per-member detail page for contacts + photo, and
        the `/committees-and-calendar` and `/staff` subpages.

        Returns (contacts_dict, committees_list, photo_url, staff_list).
        All can be empty/None when the corresponding fetch returns
        non-200 or the page lacks the expected block. `allow_redirects=False`
        because seattle.gov 301s former-member URLs to their successor
        (`sara-nelson` → `dionne-foster`); only a 200 means the URL
        really belongs to this person."""
        contacts: dict = {}
        committees: list[dict] = []
        photo_url: str | None = None
        staff: list[dict] = []
        try:
            r = requests.get(profile_url, timeout=10, allow_redirects=False)
            if r.status_code == 200:
                contacts = extract_contact_details(r.text)
                photo_url = extract_photo_url(r.text)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch {profile_url}: {e}")
        try:
            r = requests.get(profile_url + "/committees-and-calendar",
                             timeout=10, allow_redirects=False)
            if r.status_code == 200:
                committees = extract_committee_assignments(r.text)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch committees for {profile_url}: {e}")
        try:
            r = requests.get(profile_url + "/staff",
                             timeout=10, allow_redirects=False)
            if r.status_code == 200:
                staff = extract_staff(r.text)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch staff for {profile_url}: {e}")
        return contacts, committees, photo_url, staff

    def scrape(self):
        """Scrape Seattle City Council members from seattle.gov.

        Yields (in order, although pupa import sorts by type):
        - One `Organization` per unique committee (classification
          `committee`), deduped across all members by URL slug
        - One `Person` per councilmember, with the existing
          `Seattle City Council` membership plus one membership per
          committee with the role recorded as `Chair`, `Vice-Chair`,
          or `Member`."""
        url = "https://www.seattle.gov/council/members"
        response = requests.get(url)
        html = lxml_html.fromstring(response.content)

        member_items = html.xpath(
            '//ul/li[contains(text(), "District") or contains(text(), "Position")]'
        )

        # Pass 1: collect everything we need per member into a flat list.
        members_data: list[dict] = []
        for item in member_items:
            text = item.text_content().strip()
            match = re.match(r"(District|Position) (\d+):\s*(.+)", text)
            if not match:
                logger.warning(f"Could not parse council member info from text: {text}")
                continue
            district_type, number, name = match.group(1), match.group(2), match.group(3).strip()
            district = f"{district_type} {number}"
            profile_url = f"{url}/{profile_slug(name)}"
            contacts, committees, photo_url, staff = self._fetch_member_extras(profile_url)
            members_data.append({
                "name": name,
                "district": district,
                "profile_url": profile_url,
                "contacts": contacts,
                "committees_raw": committees,
                "photo_url": photo_url,
                "staff": staff,
            })

        # Build canonical_committees map: committee names on seattle.gov
        # vary in punctuation across reps' pages, and at least one page
        # has a copy-paste href/text mismatch — the URL slug is the
        # stable identifier. Pick the first-seen display name as
        # canonical (consistent across the scrape and reasonable for UI).
        canonical_committees: dict[str, dict] = {}
        for m in members_data:
            for c in m["committees_raw"]:
                slug = c["slug"]
                if slug not in canonical_committees:
                    canonical_committees[slug] = {"name": c["name"], "url": c["url"]}

        # Yield each committee Organization once.
        for slug, data in canonical_committees.items():
            org = Organization(
                name=data["name"],
                classification="committee",
            )
            org.add_source(data["url"])
            yield org

        # Yield each Person with all their memberships (council seat
        # + 1 per committee) and contact details.
        for m in members_data:
            name = m["name"]
            district = m["district"]
            contacts = m["contacts"]
            person = Person(name=name, district=district, role="Councilmember")
            if m["photo_url"]:
                person.image = m["photo_url"]
            if m["staff"]:
                # Stash the staff list on Person.extras as a JSON list
                # of `{name, title, email}` dicts. Staff aren't first-
                # class OCD entities (we don't surface them as Person
                # records, search them, link them to bills, etc.) — just
                # display data attached to the rep.
                person.extras["staff"] = m["staff"]
            person.add_membership(
                "Seattle City Council",
                role="Councilmember",
                label=district,
            )
            person.add_source(url)
            person.add_link(m["profile_url"], note="City Council profile")

            # Contacts — see extract_contact_details for shape.
            email = contacts.get("email") or f"{name.replace(' ', '.').lower()}@seattle.gov"
            person.add_contact_detail(type="email", value=email, note="Official email")
            if "phone" in contacts:
                person.add_contact_detail(type="voice", value=contacts["phone"], note="Office phone")
            if "fax" in contacts:
                person.add_contact_detail(type="fax", value=contacts["fax"], note="Office fax")
            if "office_address" in contacts:
                person.add_contact_detail(type="address", value=contacts["office_address"], note="Office")
            if "mailing_address" in contacts:
                person.add_contact_detail(type="address", value=contacts["mailing_address"], note="Mailing")

            # Committee memberships — resolve to the canonical name
            # so all 9 reps' memberships agree on org identity.
            for c in m["committees_raw"]:
                canonical_name = canonical_committees[c["slug"]]["name"]
                person.add_membership(canonical_name, role=c["role"])

            self.info(f"Scraped person: {name} ({district}) — "
                      f"{len(m['committees_raw'])} committee memberships")
            yield person

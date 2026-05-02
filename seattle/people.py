from pupa.scrape import Scraper, Person
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


    def scrape(self):
        """
        Scrape Seattle City Council members from official seattle.gov site
        """
        url = "https://www.seattle.gov/council/members"

        response = requests.get(url)
        html = lxml_html.fromstring(response.content)

        # Find all councilmember sections
        # The page has "District X:" or "Position X:" followed by name links
        member_items = html.xpath('//ul/li[contains(text(), "District") or contains(text(), "Position")]')

        for item in member_items:
            text = item.text_content().strip()

            # Parse district/position and name
            match = re.match(r'(District|Position) (\d+):\s*(.+)', text)

            if match:
                district_type = match.group(1)
                number = match.group(2)
                name = match.group(3).strip()

                district = f"{district_type} {number}"

                person = Person(
                    name=name,
                    district=district,
                    role="Councilmember"
                )

                # Add membership to the organization
                # Reference the organization by name
                # Use the district variable which contains "District X" or "Position X"
                person.add_membership(
                    "Seattle City Council",
                    role="Councilmember",
                    label=district
                )

                person.add_source(url)

                # Build profile link — per-member detail page on seattle.gov
                profile_url = f"{url}/{profile_slug(name)}"
                person.add_link(profile_url, note="City Council profile")

                # Pull contact details from the per-member detail page.
                # Falls back to a constructed `firstname.lastname@seattle.gov`
                # email if the profile fetch or parse fails — not ideal for
                # multi-name members like Alexis Mercedes Rinck (real
                # canonical form is `AlexisMercedes.Rinck@seattle.gov`)
                # but better than nothing.
                # `allow_redirects=False`: seattle.gov 301s a former
                # member's URL to their successor's page (e.g.
                # `/sara-nelson` → `/dionne-foster`), and we don't want
                # to attribute the successor's contact info to the
                # former member's record. A 200 means this URL really
                # belongs to this person.
                contacts = {}
                try:
                    profile_resp = requests.get(profile_url, timeout=10, allow_redirects=False)
                    if profile_resp.status_code == 200:
                        contacts = extract_contact_details(profile_resp.text)
                except requests.RequestException as e:
                    logger.warning(f"Could not fetch {profile_url}: {e}")

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

                self.info(f"Scraped person: {name} ({district})")

                yield person
            else:
                logger.warning(f"Could not parse council member info from text: {text}")
        pass

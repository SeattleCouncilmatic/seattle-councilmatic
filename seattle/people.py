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
                person.add_contact_detail(
                    type="email",
                    value=f"{name.replace(' ', '.').lower()}@seattle.gov",
                    note="Official email"
                )
                
                # Build profile link — per-member detail page on seattle.gov
                profile_url = f"{url}/{profile_slug(name)}"
                person.add_link(profile_url, note="City Council profile")

                self.info(f"Scraped person: {name} ({district})")

                yield person
            else:
                logger.warning(f"Could not parse council member info from text: {text}")
        pass

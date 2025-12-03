from datetime import datetime, timezone
from typing import Any
import requests

from pupa.scrape import Bill, Scraper

CLIENT = "seattle"
BASE_URL = f"https://webapi.legistar.com/v1/{CLIENT}"
ENDPOINT = "matters"
YEAR = 2025  # for prototyping will get the bills from this year

MatterDict = dict[str, Any]


class SeattleBillScraper(Scraper):
    def scrape(self):
        """Yield parsed Bill objects from fetched matters.

        Yields:
            Bill: A parsed Bill object.
        """
        bills = self.fetch_bills()
        if bills is None:
            self.warning("Failed to fetch bills from API")
            return

        for matter in bills:
            yield self.parse_matter(matter)

    def fetch_bills(self) -> list[MatterDict] | None:
        """Fetch legislative matters from the Legistar API.

        Returns:
            List[Dict[str, Any]]: A list of matter records.
        """
        url = f"{BASE_URL}/{ENDPOINT}"
        parameters = {
            "$filter": f"year(MatterIntroDate) eq {YEAR} and (MatterTypeName eq 'Council Bill (CB)' or MatterTypeName eq 'Ordinance (Ord)' or MatterTypeName eq 'Resolution (Res)')",
            "$orderby": "MatterIntroDate desc",
        }
        try:
            response = requests.get(url, params=parameters)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print("API call failed:", e)
            return None

    def parse_matter(self, matter: MatterDict) -> Bill:
        """Convert a matter JSON record into a Pupa Bill object.

        Parameters:
            matter: A dictionary containing API data for a single matter.

        Returns:
            Bill: A populated Pupa Bill object.
        """
        classification = self.classify_matter(matter)
        bill = Bill(
            identifier=matter.get("MatterFile"),
            legislative_session=str(YEAR),
            title=matter.get("MatterTitle"),
            classification=[classification],
        )

        intro_date = self.parse_date(matter.get("MatterIntroDate"))
        if intro_date:
            bill.add_action(description="Introduced", date=intro_date)

        bill.add_source(f"{BASE_URL}/{ENDPOINT}/{matter.get('MatterId')}")
        bill.extras = {
            "MatterId": matter.get("MatterId"),
            "MatterTypeName": matter.get("MatterTypeName"),
            "MatterStatusName": matter.get("MatterStatusName"),
            "MatterBodyName": matter.get("MatterBodyName"),
            "MatterLastModifiedUtc": matter.get("MatterLastModifiedUtc"),
        }
        return bill

    def classify_matter(self, matter: MatterDict) -> str:
        """Return the classification string for the matter.

        Parameters:
            matter: A dictionary containing API data for a matter.

        Returns:
            str: "bill", "ordinance", "resolution", or "other".
        """
        matter_type = matter.get("MatterTypeName", "")

        if matter_type == "Council Bill (CB)":
            return "bill"
        elif matter_type == "Ordinance (Ord)":
            return "ordinance"
        elif matter_type == "Resolution (Res)":
            return "resolution"
        else:
            if matter_type:
                self.warning(f"Unknown matter type: {matter_type}")
            return "other"

    def parse_date(self, value: str | None) -> datetime | None:
        """Parse an ISO 8601 string into a timezone-aware datetime.

        Parameters:
            value: ISO 8601 date string.

        Returns:
            datetime | None: Parsed datetime or None if invalid.
        """
        if value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

                # If date doesn't have timezone info, add UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                return dt
            except (ValueError, AttributeError) as e:
                self.warning(f"Failed to parse date '{value}': {e}")
                return None
        return None

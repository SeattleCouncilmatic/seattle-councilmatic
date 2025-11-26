from datetime import datetime
from typing import Any, Dict, Generator, List

import requests

from pupa.scrape import Bill, Scraper

CLIENT = "seattle"
BASE_URL = f"https://webapi.legistar.com/v1/{CLIENT}"
ENDPOINT = "matters"
YEAR = 2025  # for prototyping will get the bills from this year


class SeattleBillScraper(Scraper):
    def scrape(self):
        """Yield parsed Bill objects from fetched matters.

        Yields:
            Bill: A parsed Bill object.
        """
        for matter in self.fetch_bills():
            yield self.parse_matter(matter)

    def fetch_bills(self) -> List[Dict[str, Any]]:
        """Fetch legislative matters from the Legistar API.

        Returns:
            List[Dict[str, Any]]: A list of matter records.
        """
        url = f"{BASE_URL}/{ENDPOINT}"
        parameters = {
            "$filter": f"year(MatterIntroDate) eq {YEAR} and (MatterTypeName eq 'Council Bill (CB)' or MatterTypeName eq 'Ordinance (OR)' or MatterTypeName eq 'Resolution (Res)')",
            "$orderby": "MatterIntroDate desc",
        }
        try:
            response = requests.get(url, params=parameters)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print("API call failed:", e)
            return None

    def parse_matter(self, matter: Dict[str, Any]) -> Bill:
        """Convert a matter JSON record into a Pupa Bill object.

        Args:
            matter: A dictionary containing API data for a single matter.

        Returns:
            Bill: A populated Pupa Bill object.
        """
        classification = self.classify_matter(matter)
        bill = Bill(
            identifier=matter["MatterFile"],
            legislative_session=str(YEAR),
            title=matter["MatterTitle"],
            classification=[classification],
        )
        bill.add_source(f"{BASE_URL}/{ENDPOINT}/{matter.get('MatterId')}")
        bill.extras = {
            "MatterId": matter["MatterId"],
            "MatterTypeName": matter["MatterTypeName"],
            "MatterStatusName": matter["MatterStatusName"],
            "MatterBodyName": matter["MatterBodyName"],
            "MatterIntroDate": matter["MatterIntroDate"],
            "MatterLastModifiedUtc": matter["MatterLastModifiedUtc"],
        }
        return bill

    def classify_matter(self, matter: Dict[str, Any]) -> str:
        """Return the classification string for the matter.

        Args:
            matter: A dictionary containing API data for a matter.

        Returns:
            str: A "bill", "ordinance", or "resolution".
        """
        if matter["MatterTypeName"] == "Council Bill (CB)":
            return "bill"
        elif matter["MatterTypeName"] == "Ordinance (OR)":
            return "ordinance"
        elif matter["MatterTypeName"] == "Resolution (Res)":
            return "resolution"

    def parse_date(self, value):
        """Parse an ISO 8601 string into a datetime.

        Args:
            value: ISO 8601 date string.

        Returns:
            datetime | None: Parsed datetime or None if invalid.
        """
        if value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

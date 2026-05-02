from datetime import datetime, timedelta, timezone
from typing import Any
import requests

from pupa.scrape import Bill, Scraper

from seattle._http import request_with_retry

CLIENT = "seattle"
BASE_URL = f"https://webapi.legistar.com/v1/{CLIENT}"
ENDPOINT = "matters"

# Rolling window: bills introduced in the past 18 months
_WINDOW_DAYS = 548  # ~18 months

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
        window_start = (datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)).strftime('%Y-%m-%d')
        parameters = {
            "$filter": (
                f"MatterIntroDate ge datetime'{window_start}'"
                f" and (MatterTypeName eq 'Council Bill (CB)'"
                f" or MatterTypeName eq 'Ordinance (Ord)'"
                f" or MatterTypeName eq 'Resolution (Res)')"
            ),
            "$orderby": "MatterIntroDate desc",
        }
        try:
            response = request_with_retry(url, params=parameters)
            return response.json()
        except Exception as e:
            print("API call failed:", e)
            return None

    def fetch_matter_detail(self, matter_id: int, endpoint: str) -> list[dict]:
        """Fetch a sub-resource (sponsors, attachments, histories) for a matter.

        Parameters:
            matter_id: The Legistar MatterId integer.
            endpoint: Sub-resource name, e.g. 'sponsors', 'attachments', 'histories'.

        Returns:
            List of dicts from the API, or empty list on failure.
        """
        url = f"{BASE_URL}/{ENDPOINT}/{matter_id}/{endpoint}"
        try:
            response = request_with_retry(url)
            return response.json() or []
        except Exception as e:
            self.warning(f"Failed to fetch {endpoint} for matter {matter_id}: {e}")
            return []

    def parse_matter(self, matter: MatterDict) -> Bill:
        """Convert a matter JSON record into a Pupa Bill object.

        Parameters:
            matter: A dictionary containing API data for a single matter.

        Returns:
            Bill: A populated Pupa Bill object.
        """
        matter_id = matter.get("MatterId")
        classification = self.classify_matter(matter)
        intro_date = self.parse_date(matter.get("MatterIntroDate"))
        session = str(intro_date.year) if intro_date else str(datetime.now(timezone.utc).year)

        bill = Bill(
            identifier=matter.get("MatterFile"),
            legislative_session=session,
            title=matter.get("MatterTitle"),
            classification=[classification],
        )

        # --- Action history ---
        histories = self.fetch_matter_detail(matter_id, "histories")
        if histories:
            for h in histories:
                action_date = self.parse_date(h.get("MatterHistoryActionDate"))
                action_desc = h.get("MatterHistoryActionName") or h.get("MatterHistoryPassedFlagName", "")
                if action_date and action_desc:
                    bill.add_action(description=action_desc, date=action_date)
        elif intro_date:
            # Fall back to intro date only if no history available
            bill.add_action(description="Introduced", date=intro_date)

        # --- Sponsors ---
        sponsors = self.fetch_matter_detail(matter_id, "sponsors")
        for sponsor in sponsors:
            name = sponsor.get("MatterSponsorName")
            if name:
                primary = sponsor.get("MatterSponsorSequence", 1) == 0
                bill.add_sponsorship(
                    name=name,
                    classification="primary" if primary else "cosponsor",
                    entity_type="person",
                    primary=primary,
                )

        # --- Attachments (documents) ---
        attachments = self.fetch_matter_detail(matter_id, "attachments")
        for att in attachments:
            if not att.get("MatterAttachmentShowOnInternetPage"):
                continue
            name = att.get("MatterAttachmentName", "Attachment")
            url = att.get("MatterAttachmentHyperlink", "")
            if url:
                bill.add_document_link(
                    note=name,
                    url=url,
                    media_type=self._media_type(att.get("MatterAttachmentFileName", "")),
                )

        bill.add_source(f"{BASE_URL}/{ENDPOINT}/{matter_id}")

        # Public-facing Legistar URL is constructed at API-response
        # time from `MatterId` (see seattle_app.api_views.legislation_detail).
        # The Legistar matters endpoint doesn't expose a `MatterInSiteURL`
        # field — only events have `EventInSiteURL` — but
        # `https://seattle.legistar.com/Gateway.aspx?M=L&ID=<MatterId>`
        # resolves to the matter detail page, so we don't need to store
        # the public URL on the bill.

        bill.extras = {
            "MatterId": matter_id,
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

    def _media_type(self, filename: str) -> str:
        """Infer MIME type from file extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return {
            "pdf":  "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc":  "application/msword",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }.get(ext, "application/octet-stream")

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

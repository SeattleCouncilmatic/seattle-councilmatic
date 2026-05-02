"""
Seattle City Council Events Scraper

Fetches meeting/event data from Seattle's Legistar API and converts it into
Pupa's Event model format for Open Civic Data.  Each event is enriched with:
  - Agenda & minutes PDF URLs / statuses
  - Substantive agenda items linked to their Bill records
  - Per-item attachments (Summary & Fiscal Notes, amendments, etc.)
"""

from pupa.scrape import Scraper, Event
import requests
import datetime
import re
import time
import pytz
import logging

from seattle._http import request_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://webapi.legistar.com/v1/seattle"
TIMEZONE = pytz.timezone("America/Los_Angeles")

# Purely procedural agenda titles — skip these when building the agenda list
_PROCEDURAL_PATTERNS = [
    "call to order",
    "roll call",
    "approval of",
    "adjournment",
    "recess",
    "public comment",
    "items of business",
    "please note",
    "meeting procedures",
]


def _is_procedural(title: str) -> bool:
    t = (title or "").lower().strip()
    return any(t.startswith(p) for p in _PROCEDURAL_PATTERNS)


def _infer_media_type(url: str) -> str:
    url_lower = (url or "").lower()
    if url_lower.endswith(".pdf"):
        return "application/pdf"
    if url_lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if url_lower.endswith(".doc"):
        return "application/msword"
    return "application/octet-stream"


class SeattleEventScraper(Scraper):
    """Scrapes Seattle City Council events (meetings) from the Legistar API."""

    # Rolling window: 3 months back → 6 months ahead
    WINDOW_BACK_DAYS  = 90
    WINDOW_AHEAD_DAYS = 180

    # Polite delay between per-event API calls (seconds)
    API_SLEEP = 0.1

    def scrape(self):
        events = self._fetch_events()
        seen_events = set()

        for api_event in events:
            event_key = (
                api_event.get("EventBodyName", "Meeting"),
                api_event["EventDate"],
            )
            if event_key in seen_events:
                continue
            seen_events.add(event_key)

            event = self._parse_event(api_event)
            if event:
                yield event

    # ------------------------------------------------------------------ #
    #  Fetching                                                            #
    # ------------------------------------------------------------------ #

    def _fetch_events(self) -> list[dict]:
        today        = datetime.datetime.utcnow()
        window_start = today - datetime.timedelta(days=self.WINDOW_BACK_DAYS)
        window_end   = today + datetime.timedelta(days=self.WINDOW_AHEAD_DAYS)

        params = {
            "$filter": (
                f"EventDate ge datetime'{window_start.strftime('%Y-%m-%d')}'"
                f" and EventDate le datetime'{window_end.strftime('%Y-%m-%d')}'"
            ),
            "$orderby": "EventDate asc",
        }
        # No swallow on the bulk events fetch: if all retries fail, let
        # the ScrapeError bubble. An empty `[]` here was the failure mode
        # that crashed the entire daily sync on 2026-05-02 — we'd rather
        # see the network exception than mask it as "no events".
        resp = request_with_retry(f"{BASE_URL}/events", params=params, timeout=30)
        events = resp.json()
        logger.info(f"Fetched {len(events)} events from Legistar API")
        return events

    def _fetch_packet_url(self, legistar_page_url: str) -> str | None:
        """
        Scrape the public Legistar meeting page to extract the Agenda Packet URL.
        The packet URL is not in the REST API — it only appears in the HTML.
        """
        try:
            resp = request_with_retry(legistar_page_url, timeout=15)
            match = re.search(
                r'id="ctl00_ContentPlaceHolder1_hypAgendaPacket"\s+href="([^"]+)"',
                resp.text,
            )
            if match:
                relative = match.group(1).replace("&amp;", "&")
                return "https://seattle.legistar.com/" + relative
        except Exception as e:
            logger.warning(f"Could not fetch packet URL from {legistar_page_url}: {e}")
        return None

    def _fetch_event_items(self, event_id: int) -> list[dict]:
        """Fetch agenda items for a single event, including attachments."""
        try:
            url = f"{BASE_URL}/events/{event_id}/eventitems"
            resp = request_with_retry(
                url,
                params={"AgendaNote": 1, "MinutesNote": 1, "Attachments": 1},
                timeout=30,
            )
            return resp.json() or []
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch event items for event {event_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Parsing                                                             #
    # ------------------------------------------------------------------ #

    def _parse_event(self, api_event: dict):
        try:
            event_id   = api_event["EventId"]
            event_name = api_event.get("EventBodyName", "Meeting")
            event_date_str = api_event["EventDate"]
            event_time_str = (api_event.get("EventTime") or "").strip()
            location   = api_event.get("EventLocation", "Location TBD")

            # Legistar splits the meeting timestamp across two fields:
            # EventDate always carries midnight; the wall-clock time lives
            # in EventTime as a 12-hour string like "9:30 AM". Fall back to
            # midnight if EventTime is missing or unparseable so a malformed
            # row doesn't drop the whole event.
            event_date = datetime.datetime.strptime(event_date_str, "%Y-%m-%dT%H:%M:%S")
            if event_time_str:
                try:
                    event_time = datetime.datetime.strptime(event_time_str, "%I:%M %p").time()
                    event_date = event_date.replace(hour=event_time.hour, minute=event_time.minute)
                except ValueError:
                    logger.warning(
                        f"Could not parse EventTime {event_time_str!r} for event {event_id}; "
                        f"falling back to midnight"
                    )
            event_date = TIMEZONE.localize(event_date)

            event = Event(
                name=event_name,
                start_date=event_date,
                location_name=location,
            )

            # Core Legistar ID
            event.extras["legistar_event_id"] = event_id

            # Agenda & minutes document URLs / statuses
            event.extras["agenda_file_url"]  = api_event.get("EventAgendaFile") or None
            event.extras["agenda_status"]    = api_event.get("EventAgendaStatusName") or None
            event.extras["minutes_file_url"] = api_event.get("EventMinutesFile") or None
            event.extras["minutes_status"]   = api_event.get("EventMinutesStatusName") or None

            # Public-facing Legistar URL (used by the frontend detail page)
            in_site_url = api_event.get("EventInSiteURL")
            if in_site_url:
                event.add_source(in_site_url)

            # Agenda items (one extra API call per event)
            self._add_agenda_items(event, event_id)

            # Agenda Packet URL — only available via HTML scrape of the Legistar page
            if in_site_url:
                event.extras["packet_url"] = self._fetch_packet_url(in_site_url)

            time.sleep(self.API_SLEEP)

            logger.info(f"Parsed event: {event_name} on {event_date.date()}")
            return event

        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse event {api_event.get('EventId')}: {e}")
            return None

    def _add_agenda_items(self, event: Event, event_id: int):
        """
        Fetch agenda items for this event and attach substantive ones to the
        Pupa Event object.  Purely procedural items (call to order, etc.) are
        skipped.
        """
        raw_items = self._fetch_event_items(event_id)

        for raw in raw_items:
            title      = (raw.get("EventItemTitle") or "").strip()
            matter_id  = raw.get("EventItemMatterId")
            matter_file = (raw.get("EventItemMatterFile") or "").strip()
            seq        = raw.get("EventItemAgendaSequence") or 0

            # Skip items with no title
            if not title:
                continue

            # Skip purely procedural items that have no associated matter
            if not matter_id and _is_procedural(title):
                continue

            agenda_item = event.add_agenda_item(description=title)
            agenda_item["order"] = str(seq)

            # Store Legistar metadata in extras for the API to surface
            agenda_item["extras"] = {
                "legistar_matter_id": matter_id,
                "matter_file":        matter_file or None,
                "matter_type":        raw.get("EventItemMatterType") or None,
                "matter_status":      raw.get("EventItemMatterStatus") or None,
                "passed_flag":        raw.get("EventItemPassedFlag"),
                "action_text":        raw.get("EventItemActionText") or None,
            }

            # Link to the bill by its file identifier (e.g. "CB 121164")
            # pupa will match this against Bill.identifier during import
            if matter_file:
                agenda_item.add_bill(matter_file, note="consideration")

            # Attachments (Summary & Fiscal Note, amendments, etc.)
            for att in raw.get("EventItemMatterAttachments") or []:
                name = (att.get("MatterAttachmentName") or "").strip()
                url  = (att.get("MatterAttachmentHyperlink") or "").strip()
                if name and url:
                    media_type = _infer_media_type(url)
                    try:
                        agenda_item.add_media_link(
                            note=name,
                            url=url,
                            media_type=media_type,
                            on_duplicate="ignore",
                        )
                    except Exception as e:
                        logger.debug(f"Could not add media link '{name}': {e}")

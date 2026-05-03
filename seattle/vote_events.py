"""Seattle City Council Vote Events Scraper.

Walks past Legistar events in a 548-day window (matches the bills
scraper) and yields one Pupa VoteEvent per substantive eventitem
that recorded a roll-call vote.

Data shape (per probe of the live API):

* `/events?$filter=EventDate ge ...` → list of events
* `/events/<EventId>/eventitems` → agenda items for an event; each
  item with a `EventItemMatterId` is a substantive bill consideration
* `/eventitems/<EventItemId>/votes` → per-person votes for that item

Each per-person vote carries a `VoteValueName` like "In Favor" /
"Opposed" / "Absent(NV)"; we normalize these to pupa's standard vote
options (`yes`, `no`, `abstain`, `absent`, `excused`, `not voting`,
`other`). The eventitem's `EventItemPassedFlagName` ("Pass" / "Fail")
gives the aggregate result; `EventItemActionText` gives the human-
readable motion text.
"""

from __future__ import annotations

import datetime
import logging

import pytz
import requests
from pupa.scrape import Scraper, VoteEvent

from seattle._http import request_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://webapi.legistar.com/v1/seattle"
TIMEZONE = pytz.timezone("America/Los_Angeles")

# Match the bills scraper's window so we cover every bill currently
# in the DB. Looking only backwards — votes don't exist on future
# events.
_WINDOW_BACK_DAYS = 548

# MatterFile prefixes we have Bill records for (matches the bills
# scraper's filter — Council Bills, Ordinances, Resolutions). Votes
# on items outside this set (appointments, minutes adoption, IRC
# adoption, clerk files, etc.) get skipped because they have no Bill
# to link to and pupa's importer would crash trying to resolve them.
_TRACKED_MATTER_PREFIXES = ("CB ", "Ord ", "Res ")


# Map Legistar's VoteValueName to pupa's standard vote option strings.
# Defaults to "other" so unfamiliar values don't drop the vote silently.
_VOTE_VALUE_MAP = {
    "In Favor":    "yes",
    "Yea":         "yes",
    "Aye":         "yes",
    "Opposed":     "no",
    "Against":     "no",
    "Nay":         "no",
    "Abstain":     "abstain",
    "Absent":      "absent",
    "Absent(NV)":  "absent",
    "Excused":     "excused",
    "Excused-NV":  "excused",
    "NonMember-NV":  "not voting",
    "Not Voting":  "not voting",
    "Recused":     "not voting",
}


def _vote_option(value_name: str | None) -> str:
    if not value_name:
        return "other"
    return _VOTE_VALUE_MAP.get(value_name.strip(), "other")


def _result(passed_flag_name: str | None) -> str:
    """Map `EventItemPassedFlagName` to pupa's `result` field."""
    if not passed_flag_name:
        return "fail"
    return "pass" if passed_flag_name.strip().lower() == "pass" else "fail"


class SeattleVoteEventScraper(Scraper):
    """Scrapes per-person roll-call votes from Legistar."""

    API_SLEEP = 0.05

    def scrape(self):
        # Pre-load the set of `(identifier, session)` pairs we have as
        # Bill records so we can skip votes referencing bills outside
        # our scrape window. Pupa's vote_event importer calls
        # `bill_importer.resolve_json_id(bill)` without
        # `allow_no_match=True`, so an unresolved bill crashes the
        # entire import — we have to filter before yielding.
        # Bills in the scrape window: CB / Ord / Res introduced in the
        # last 548 days (matches `seattle/bills.py:_WINDOW_DAYS`); a
        # vote that lands in our 548-day window can still reference an
        # older bill, which we have to drop.
        known_bills = self._load_known_bill_identifiers()
        logger.info(f"Filtering votes against {len(known_bills)} known bill identifiers")

        for ev in self._fetch_events():
            yield from self._scrape_event_votes(ev, known_bills)

    def _load_known_bill_identifiers(self) -> set[tuple[str, str]]:
        """Return `{(identifier, session_identifier), ...}` for every
        Bill in the DB. Uses raw SQL so we don't pull a Django ORM
        dependency from inside a pupa scraper."""
        # Local import avoids a Django settings load at module import
        # time when this scraper is just being introspected.
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("""
                SELECT b.identifier, ls.identifier
                FROM opencivicdata_bill b
                JOIN opencivicdata_legislativesession ls ON ls.id = b.legislative_session_id
            """)
            return {(ident, sess) for ident, sess in cur.fetchall()}

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #

    def _fetch_events(self) -> list[dict]:
        today = datetime.datetime.now(datetime.timezone.utc)
        window_start = today - datetime.timedelta(days=_WINDOW_BACK_DAYS)
        params = {
            "$filter": (
                f"EventDate ge datetime'{window_start.strftime('%Y-%m-%d')}'"
                f" and EventDate le datetime'{today.strftime('%Y-%m-%d')}'"
            ),
            "$orderby": "EventDate asc",
        }
        resp = request_with_retry(f"{BASE_URL}/events", params=params, timeout=30)
        events = resp.json()
        logger.info(f"Fetched {len(events)} past events for vote scraping")
        return events

    def _fetch_event_items(self, event_id: int) -> list[dict]:
        try:
            resp = request_with_retry(
                f"{BASE_URL}/events/{event_id}/eventitems",
                timeout=30,
            )
            return resp.json() or []
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch eventitems for event {event_id}: {e}")
            return []

    def _fetch_item_votes(self, item_id: int) -> list[dict]:
        try:
            resp = request_with_retry(
                f"{BASE_URL}/eventitems/{item_id}/votes",
                timeout=30,
            )
            return resp.json() or []
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch votes for eventitem {item_id}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _scrape_event_votes(self, api_event: dict, known_bills: set[tuple[str, str]]):
        event_id = api_event["EventId"]
        # Legistar's `EventBodyName` covers the current council (`City
        # Council`), current committees (`Public Safety Committee`,
        # etc.), and older / now-defunct committees (`Land Use
        # Committee`, `Parks, Public Utilities, and Technology
        # Committee`, etc.) from prior council eras. We attribute every
        # vote to the parent `Seattle City Council` Organization so
        # imports never fail on an unresolved body name; the original
        # body name is preserved in extras for future committee-level
        # filtering when we want it.
        event_body = api_event.get("EventBodyName") or ""
        event_date_str = api_event["EventDate"]
        event_time_str = (api_event.get("EventTime") or "").strip()

        # Compose the wall-clock timestamp the same way the events
        # scraper does (EventDate + EventTime → Pacific localized).
        event_date = datetime.datetime.strptime(event_date_str, "%Y-%m-%dT%H:%M:%S")
        if event_time_str:
            try:
                t = datetime.datetime.strptime(event_time_str, "%I:%M %p").time()
                event_date = event_date.replace(hour=t.hour, minute=t.minute)
            except ValueError:
                pass
        event_date_local = TIMEZONE.localize(event_date)
        session = str(event_date_local.year)

        for item in self._fetch_event_items(event_id):
            matter_id = item.get("EventItemMatterId")
            matter_file = (item.get("EventItemMatterFile") or "").strip()
            if not matter_id or not matter_file:
                continue
            if not matter_file.startswith(_TRACKED_MATTER_PREFIXES):
                # Skip Appt / Min / IRC / CF / etc. — not in our Bill table.
                continue
            if (matter_file, session) not in known_bills:
                # Bill exists in Legistar but predates our 548-day bills
                # window. Skip — pupa would crash trying to resolve it.
                continue

            votes = self._fetch_item_votes(item["EventItemId"])
            if not votes:
                continue

            ve = VoteEvent(
                legislative_session=session,
                motion_text=(item.get("EventItemActionText")
                             or item.get("EventItemActionName")
                             or "Vote"),
                start_date=event_date_local.isoformat(),
                classification=[],
                result=_result(item.get("EventItemPassedFlagName")),
                bill=matter_file,
                bill_chamber=None,
                # `chamber="legislature"` is pupa's idiomatic way to
                # link a VoteEvent to its parent organization without
                # passing a string name (which gets stored literally
                # and won't resolve at import time). Pupa wraps it
                # internally as `~{"classification": "legislature"}`
                # which matches our `Seattle City Council` Org by its
                # classification at import. The original
                # `EventBodyName` is preserved in extras (below) for
                # future committee-level filtering.
                chamber="legislature",
            )
            # Preserve the original EventBodyName so we can later
            # resolve a committee-of-record per vote without a re-scrape.
            ve.extras["event_body_name"] = event_body
            ve.extras["legistar_event_id"] = event_id
            ve.extras["legistar_event_item_id"] = item["EventItemId"]
            # `bill` as a string makes pupa look up by identifier within
            # the same legislative_session — which is fine when the vote
            # year matches the bill's introduction year. For votes on
            # bills introduced in a prior session, pupa may not find a
            # match and will warn during import; acceptable for v1.

            in_site_url = api_event.get("EventInSiteURL")
            if in_site_url:
                ve.add_source(in_site_url)

            counts = {"yes": 0, "no": 0, "abstain": 0, "absent": 0,
                      "excused": 0, "not voting": 0, "other": 0}
            for v in votes:
                option = _vote_option(v.get("VoteValueName"))
                voter = (v.get("VotePersonName") or "").strip()
                if not voter:
                    continue
                ve.vote(option, voter)
                counts[option] += 1
            for option, count in counts.items():
                if count:
                    ve.set_count(option, count)

            yield ve

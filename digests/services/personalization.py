"""Personalization match queries for digest composition (Phase 2, #235).

Given one subscriber's ``SubscriberPreferences`` and a cadence window, find
the council items with news in that window. The four bill dimensions are
UNIONed — any one match includes the bill, and every dimension that matched
contributes a human-readable reason (rendered in the email and, in Phase 3,
fed to the LLM intro):

- **issue areas** — the bill's ``BillTags`` overlap the subscriber's tags.
- **followed reps** — a followed councilmember sponsored the bill.
- **district** — the subscriber's district councilmember primary-sponsored
  the bill (at-large "districts" match the Position 8/9 members).
- **followed bills** — the subscriber follows the bill itself.

Committee-meeting recaps join through people: meetings (``EventSummary``
rows, so past + summarized) of committees a followed rep or the district
rep sits on. RepSummary "updates" are deliberately NOT an item type: the
weekly rep refresh bumps ``generated_at`` for every rep whether or not
anything changed, so it can't distinguish news from regeneration — rep
activity reaches the digest through the sponsorship dimension instead.

"News in the window" means: a ``BillAction`` dated inside it (scrape-fed,
so it tracks Legistar activity), or a meeting that started inside it and
has an LLM recap. Queries run per subscriber — a handful of indexed
queries each, fine at v1 scale (hundreds of subscribers).

The compose→send handoff stores only ``[{type, id, reasons}]`` on
``DigestSend.matched_item_ids``; ``items_from_snapshot`` re-fetches content
(titles, summaries, dates) by id at render time so nothing bulky or stale
is duplicated into the row.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Max, Q

from councilmatic_core.models import Bill, Event
from opencivicdata.core.models import Membership

# Reused, not forked: normalization drift here would silently drop meeting
# matches (an event named "Public Safety Committee" must reduce to the same
# key as the Organization named "Public Safety").
from seattle_app.api_views import _normalize_committee_name

# The weekly window is 8 days, not 7: the cron fires Sunday 6 AM and
# BillAction dates are date-only strings, so a 7-day cutoff would drop
# last Sunday's actions on the boundary.
WEEKLY_WINDOW_DAYS = 8
# Daily fallback when a subscriber has never been sent anything.
DAILY_WINDOW_DAYS = 1

_COUNCIL_ORG_NAME = "Seattle City Council"


def window_start(cadence: str, subscriber, now) -> date:
    """Start date (inclusive) of the news window for this subscriber."""
    if cadence == "daily" and subscriber.last_sent_at:
        return subscriber.last_sent_at.date()
    days = DAILY_WINDOW_DAYS if cadence == "daily" else WEEKLY_WINDOW_DAYS
    return (now - timedelta(days=days)).date()


def match_items(prefs, since: date) -> list[dict]:
    """All items matching this subscriber's preferences with news since
    ``since``. Returns render-ready dicts (see ``_bill_item`` /
    ``_meeting_item``); bills first (most recent action first), then
    meeting recaps (most recent first)."""
    followed_rep_ids = list(prefs.followed_reps.values_list("id", flat=True))
    district_rep_ids = _district_rep_ids(prefs.district)
    items = _matched_bills(prefs, since, followed_rep_ids, district_rep_ids)
    items += _matched_meetings(since, followed_rep_ids, district_rep_ids)
    return items


def snapshot(items: list[dict]) -> list[dict]:
    """The persisted form: ids + compose-time reasons, no content."""
    return [
        {"type": i["type"], "id": i["id"], "reasons": i["reasons"]}
        for i in items
    ]


def items_from_snapshot(snap: list[dict]) -> list[dict]:
    """Re-fetch render-ready items for a stored snapshot. Content comes from
    the DB as of *send* time; reasons come from the snapshot (they explain
    compose-time matching, which a re-run might not reproduce). Items whose
    row has vanished (bill deleted by a re-scrape) are dropped."""
    reasons_by_key = {(s["type"], s["id"]): s["reasons"] for s in snap}
    bill_ids = [s["id"] for s in snap if s["type"] == "bill"]
    event_ids = [s["id"] for s in snap if s["type"] == "meeting"]

    items: list[dict] = []
    if bill_ids:
        bills = (
            Bill.objects.filter(id__in=bill_ids)
            .select_related("llm_summary")
            .prefetch_related("actions")
        )
        items += [
            _bill_item(b, reasons_by_key[("bill", b.id)]) for b in bills
        ]
    if event_ids:
        events = Event.objects.filter(id__in=event_ids).select_related("llm_summary")
        items += [
            _meeting_item(e, reasons_by_key[("meeting", e.id)])
            for e in events
            if getattr(e, "llm_summary", None)
        ]
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return items


# --------------------------------------------------------------------- #
# Bills
# --------------------------------------------------------------------- #

def _matched_bills(prefs, since, followed_rep_ids, district_rep_ids) -> list[dict]:
    # BillAction.date is an ISO string (sometimes date-only, sometimes full
    # timestamp), so lexicographic >= against YYYY-MM-DD is the correct
    # comparison — same idiom as api_views' date-range filters.
    recent = Bill.objects.annotate(last_action=Max("actions__date")).filter(
        last_action__gte=since.isoformat()
    )

    # One id-set per dimension so each matched bill can say WHY it matched.
    by_tag = set(
        recent.filter(issue_tags__tags__overlap=prefs.issue_areas)
        .values_list("id", flat=True)
    ) if prefs.issue_areas else set()
    by_rep = set(
        recent.filter(sponsorships__person_id__in=followed_rep_ids)
        .values_list("id", flat=True)
    ) if followed_rep_ids else set()
    # Primary sponsorship only for the district dimension: "your district's
    # councilmember signed on as cosponsor #6" isn't district news.
    by_district = set(
        recent.filter(
            sponsorships__person_id__in=district_rep_ids,
            sponsorships__primary=True,
        ).values_list("id", flat=True)
    ) if district_rep_ids else set()
    followed_bill_ids = set(prefs.followed_bills.values_list("id", flat=True))
    by_followed = set(
        recent.filter(id__in=followed_bill_ids).values_list("id", flat=True)
    ) if followed_bill_ids else set()

    matched_ids = by_tag | by_rep | by_district | by_followed
    if not matched_ids:
        return []

    rep_names = _names_for(followed_rep_ids) if by_rep else {}

    bills = (
        Bill.objects.filter(id__in=matched_ids)
        .annotate(last_action=Max("actions__date"))
        .select_related("llm_summary", "issue_tags")
        .prefetch_related("actions", "sponsorships")
        .order_by("-last_action")
    )
    items = []
    for bill in bills:
        reasons = []
        if bill.id in by_followed:
            reasons.append("You follow this bill")
        if bill.id in by_tag:
            tags = sorted(set(bill.issue_tags.tags) & set(prefs.issue_areas))
            reasons.append("Tagged " + ", ".join(tags))
        if bill.id in by_rep:
            sponsors = sorted({
                rep_names[s.person_id]
                for s in bill.sponsorships.all()
                if s.person_id in rep_names
            })
            reasons.append("Sponsored by " + ", ".join(sponsors))
        if bill.id in by_district and bill.id not in by_rep:
            reasons.append("Sponsored by your district's councilmember")
        items.append(_bill_item(bill, reasons))
    return items


def _bill_item(bill, reasons) -> dict:
    latest = max(bill.actions.all(), key=lambda a: a.date or "", default=None)
    return {
        "type": "bill",
        "id": bill.id,
        "identifier": bill.identifier,
        "title": bill.title or "",
        "url_path": f"/legislation/{bill.slug}",
        "date": (latest.date or "")[:10] if latest else "",
        "latest_action": latest.description if latest else "",
        "summary": _first_paragraph(
            getattr(getattr(bill, "llm_summary", None), "summary", "")
        ),
        "reasons": reasons,
        # Reserved for Phase 5 (DIGEST_INCLUDE_BLURBS). The template's
        # {% if item.blurb %} block stays dark until then.
        "blurb": None,
    }


# --------------------------------------------------------------------- #
# Committee meetings
# --------------------------------------------------------------------- #

def _matched_meetings(since, followed_rep_ids, district_rep_ids) -> list[dict]:
    rep_ids = list(dict.fromkeys([*followed_rep_ids, *district_rep_ids]))
    if not rep_ids:
        return []
    # normalized committee name -> which of the subscriber's reps sit on it
    committees: dict[str, set[str]] = {}
    memberships = Membership.objects.filter(
        person_id__in=rep_ids, organization__classification="committee"
    ).select_related("organization", "person")
    for m in memberships:
        key = _normalize_committee_name(m.organization.name)
        committees.setdefault(key, set()).add(m.person.name)
    if not committees:
        return []

    # Meetings with an LLM recap are past meetings by construction (the
    # summary needs a transcript), so no upper date bound is needed.
    events = (
        Event.objects.filter(
            start_date__gte=since.isoformat(), llm_summary__isnull=False
        )
        .select_related("llm_summary")
        .order_by("-start_date")
    )
    items = []
    for event in events:
        reps = committees.get(_normalize_committee_name(event.name))
        if not reps:
            continue
        reasons = ["Committee meeting of " + ", ".join(sorted(reps))]
        items.append(_meeting_item(event, reasons))
    return items


def _meeting_item(event, reasons) -> dict:
    return {
        "type": "meeting",
        "id": event.id,
        "identifier": "",
        "title": event.name,
        "url_path": f"/events/{event.slug}",
        "date": (event.start_date or "")[:10],
        "latest_action": "",
        "summary": _first_paragraph(event.llm_summary.overview),
        "reasons": reasons,
        "blurb": None,
    }


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

def _district_rep_ids(district) -> list[str]:
    """Person ids of the current councilmember(s) for a ``reps.District``.
    Geographic districts map to the membership labeled "District <n>";
    the "At Large" district maps to the citywide Position seats."""
    if district is None:
        return []
    if district.number == "At Large":
        seat_q = Q(label__startswith="Position")
    else:
        seat_q = Q(label=f"District {district.number}")
    active_q = Q(end_date="") | Q(end_date__gte=date.today().isoformat())
    return list(
        Membership.objects.filter(
            seat_q, active_q, organization__name=_COUNCIL_ORG_NAME
        ).values_list("person_id", flat=True)
    )


def _names_for(person_ids) -> dict[str, str]:
    from opencivicdata.core.models import Person

    return dict(Person.objects.filter(id__in=person_ids).values_list("id", "name"))


def _first_paragraph(text: str) -> str:
    """First paragraph of a multi-paragraph DB summary — digests are scannable;
    the linked detail page has the rest. Content is verbatim, just truncated
    at the paragraph boundary."""
    return (text or "").strip().split("\n\n", 1)[0]

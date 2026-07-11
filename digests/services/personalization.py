"""Personalization match queries for digest composition (Phase 2, #235).

Given one subscriber's ``SubscriberPreferences`` and a cadence window, find
the council items with news in that window. The four bill dimensions are
UNIONed — any one match includes the bill, and every dimension that matched
contributes a human-readable reason (rendered in the email and, in Phase 3,
fed to the LLM intro):

- **issue areas** — the bill's ``BillTags`` overlap the subscriber's tags.
- **representatives** — one of the subscriber's representatives sponsored
  the bill. The (required) district maps to a representative set the same
  way the council-map page does: the district's seat holder plus the
  citywide Position members ("At Large" districts get the citywide members
  only). Reasons name the sponsor and mark which hat they wear ("your
  district's councilmember" / "(citywide)").
- **followed reps / followed bills** — legacy dimensions: the subscribe
  form no longer collects either, but the M2M fields remain on the model
  and rows that carry them still match.

Committee-meeting recaps join through people: meetings (``EventSummary``
rows, so past + summarized) of committees any of the subscriber's
representatives (or legacy followed reps) sit on. RepSummary "updates" are
deliberately NOT an item type: the
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

from datetime import date, datetime, timedelta

from django.db.models import Max, Q
from django.utils import timezone

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
    representatives = _representatives_of(prefs.district)
    items = _matched_bills(prefs, since, followed_rep_ids, representatives)
    items += _matched_meetings(
        since, followed_rep_ids, list(representatives)
    )
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
            .select_related("llm_summary", "issue_tags")
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

def _matched_bills(prefs, since, followed_rep_ids, representatives) -> list[dict]:
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
    by_representative = set(
        recent.filter(sponsorships__person_id__in=list(representatives))
        .values_list("id", flat=True)
    ) if representatives else set()
    followed_bill_ids = set(prefs.followed_bills.values_list("id", flat=True))
    by_followed = set(
        recent.filter(id__in=followed_bill_ids).values_list("id", flat=True)
    ) if followed_bill_ids else set()

    matched_ids = by_tag | by_rep | by_representative | by_followed
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
        sponsor_ids = {
            s.person_id for s in bill.sponsorships.all() if s.person_id
        }
        # Representative sponsors get one named reason each, district seat
        # first — the phrasing carries into the email pills and the LLM's
        # matched_because, so the model never has to guess who "your
        # district's councilmember" is.
        rep_covered: set[str] = set()
        if bill.id in by_representative:
            for pid in sorted(
                sponsor_ids & set(representatives),
                key=lambda p: (representatives[p]["citywide"],
                               representatives[p]["name"]),
            ):
                info = representatives[pid]
                if info["citywide"]:
                    reasons.append(f"Sponsored by {info['name']} (citywide)")
                else:
                    reasons.append(
                        f"Sponsored by {info['name']}, your district's councilmember"
                    )
                rep_covered.add(pid)
        if bill.id in by_rep:
            # Legacy followed reps not already covered by the
            # representative mapping.
            sponsors = sorted({
                rep_names[pid]
                for pid in sponsor_ids
                if pid in rep_names and pid not in rep_covered
            })
            if sponsors:
                reasons.append("Sponsored by " + ", ".join(sponsors))
        items.append(_bill_item(bill, reasons))
    return items


def _bill_item(bill, reasons) -> dict:
    latest = max(bill.actions.all(), key=lambda a: a.date or "", default=None)
    tags = list(getattr(getattr(bill, "issue_tags", None), "tags", []) or [])
    # Tag-dimension matches render as highlighted topic pills, not as a
    # "Tagged X" sentence pill — recover the matched tag names from the
    # reason string so items_from_snapshot (which has no prefs in scope)
    # gets the same split.
    matched_tags: set[str] = set()
    for reason in reasons:
        if reason.startswith("Tagged "):
            matched_tags.update(reason[len("Tagged "):].split(", "))
    return {
        "type": "bill",
        "id": bill.id,
        "identifier": bill.identifier,
        "title": bill.title or "",
        "short_title": _short_title(bill.title or ""),
        "subtitle": _title_subtitle(bill.title or ""),
        "url_path": f"/legislation/{bill.slug}",
        "date": (latest.date or "")[:10] if latest else "",
        "latest_action": latest.description if latest else "",
        "summary": _first_paragraph(
            getattr(getattr(bill, "llm_summary", None), "summary", "")
        ),
        "reasons": reasons,
        # Rendering split: every bill tag becomes a topic pill (matched
        # ones highlighted); non-tag reasons stay sentence pills.
        "tags": [
            {"name": t, "matched": t in matched_tags} for t in tags
        ],
        "display_reasons": [
            r for r in reasons if not r.startswith("Tagged ")
        ],
        # Reserved for Phase 5 (DIGEST_INCLUDE_BLURBS). The template's
        # {% if item.blurb %} block stays dark until then.
        "blurb": None,
    }


# --------------------------------------------------------------------- #
# Committee meetings
# --------------------------------------------------------------------- #

def _committees_of(rep_ids) -> dict[str, set[str]]:
    """normalized committee name -> which of the subscriber's reps sit on it"""
    committees: dict[str, set[str]] = {}
    memberships = Membership.objects.filter(
        person_id__in=rep_ids, organization__classification="committee"
    ).select_related("organization", "person")
    for m in memberships:
        key = _normalize_committee_name(m.organization.name)
        committees.setdefault(key, set()).add(m.person.name)
    return committees


def _matched_meetings(since, followed_rep_ids, representative_ids) -> list[dict]:
    rep_ids = list(dict.fromkeys([*followed_rep_ids, *representative_ids]))
    if not rep_ids:
        return []
    committees = _committees_of(rep_ids)
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
        "short_title": event.name,
        "subtitle": "",
        "url_path": f"/events/{event.slug}",
        "date": (event.start_date or "")[:10],
        "latest_action": "",
        "summary": _first_paragraph(event.llm_summary.overview),
        "reasons": reasons,
        "tags": [],
        "display_reasons": reasons,
        "blurb": None,
    }


# --------------------------------------------------------------------- #
# Upcoming meetings (the email's "Coming up" sidebar)
# --------------------------------------------------------------------- #

# How far ahead the sidebar looks, and how many meetings it lists.
UPCOMING_HORIZON_DAYS = 8
UPCOMING_LIMIT = 5


def upcoming_meetings(prefs) -> list[dict]:
    """Scheduled (non-cancelled) meetings in the coming week for committees
    a followed rep or the district rep sits on. Computed fresh at SEND time,
    not snapshotted at compose — forward-looking content must not go stale
    between the two, and quiet-week digests render it too (it's what makes
    a quiet week still worth opening)."""
    followed_rep_ids = list(prefs.followed_reps.values_list("id", flat=True))
    rep_ids = list(dict.fromkeys(
        [*followed_rep_ids, *_representatives_of(prefs.district)]
    ))
    if not rep_ids:
        return []
    committees = _committees_of(rep_ids)
    if not committees:
        return []

    now = timezone.now()
    horizon = now + timedelta(days=UPCOMING_HORIZON_DAYS)
    events = (
        Event.objects.filter(
            start_date__gte=now.isoformat(),
            start_date__lte=horizon.isoformat(),
        )
        .exclude(status="cancelled")
        .order_by("start_date")
    )
    items = []
    for event in events:
        reps = committees.get(_normalize_committee_name(event.name))
        if not reps:
            continue
        when = _parse_start(event.start_date)
        items.append({
            "type": "upcoming",
            "id": event.id,
            "title": event.name,
            "url_path": f"/events/{event.slug}",
            "date_label": (
                when.strftime("%a, %b %d") if when
                else (event.start_date or "")[:10]
            ),
            "time_label": (
                when.strftime("%I:%M %p").lstrip("0")
                if when and (when.hour or when.minute) else ""
            ),
            "reps": sorted(reps),
        })
        if len(items) >= UPCOMING_LIMIT:
            break
    return items


def _parse_start(start_date: str):
    """Event.start_date is a CharField of full ISO 8601 (usually with a
    timezone). Localized for display; None when unparseable."""
    try:
        when = datetime.fromisoformat(start_date)
    except (TypeError, ValueError):
        return None
    if timezone.is_aware(when):
        when = timezone.localtime(when)
    return when


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

def _representatives_of(district) -> dict[str, dict]:
    """``{person_id: {"name", "citywide"}}`` for the subscriber's
    representatives — the district's seat holder plus the citywide Position
    members, mirroring how the council-map page answers "who represents
    me?". An "At Large" district has no district seat, so it maps to the
    citywide members only."""
    if district is None:
        return {}
    seat_q = Q(label__startswith="Position")
    if district.number != "At Large":
        seat_q |= Q(label=f"District {district.number}")
    active_q = Q(end_date="") | Q(end_date__gte=date.today().isoformat())
    reps: dict[str, dict] = {}
    memberships = Membership.objects.filter(
        seat_q, active_q, organization__name=_COUNCIL_ORG_NAME
    ).select_related("person")
    for m in memberships:
        reps[m.person_id] = {
            "name": m.person.name,
            "citywide": m.label.startswith("Position"),
        }
    return reps


def _names_for(person_ids) -> dict[str, str]:
    from opencivicdata.core.models import Person

    return dict(Person.objects.filter(id__in=person_ids).values_list("id", "name"))


def _first_paragraph(text: str) -> str:
    """First paragraph of a multi-paragraph DB summary — digests are scannable;
    the linked detail page has the rest. Content is verbatim, just truncated
    at the paragraph boundary."""
    return (text or "").strip().split("\n\n", 1)[0]


# Caps for the digest card header/subtitle derived from a bill's legal title.
SHORT_TITLE_MAX = 110
SUBTITLE_MAX = 160


def _clause_truncate(clause: str, max_len: int) -> str:
    clause = clause.strip()
    if len(clause) <= max_len:
        return clause
    cut = clause[:max_len].rsplit(" ", 1)[0].rstrip(",.:")
    return f"{cut}…"


def _short_title(title: str) -> str:
    """Digest card header from a Seattle legal title. These run to hundreds
    of chars of semicolon-chained boilerplate ("An ordinance relating to the
    City Light Department; authorizing the General Manager and Chief
    Executive Officer to grant an easement over…"), and the first
    semicolon clause is the informative topic — so take that, then
    word-boundary truncate in case the clause itself runs long (some
    resolutions have no semicolon at all). The linked bill page has the
    full title."""
    return _clause_truncate(title.split(";", 1)[0], SHORT_TITLE_MAX)


def _title_subtitle(title: str) -> str:
    """The second semicolon clause — usually the operative verb phrase
    ("authorizing the General Manager … to grant an easement …") — rendered
    as the card's smaller subtitle. Clauses past the second semicolon are
    boilerplate ("ratifying and confirming certain prior acts") and stay
    out. Empty when the title has no semicolon."""
    parts = title.split(";")
    if len(parts) < 2:
        return ""
    return _clause_truncate(parts[1], SUBTITLE_MAX)

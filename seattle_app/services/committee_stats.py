"""Structured context + change-detection hash for committee LLM summaries
(``summarize_committees``).

The context mirrors what ``reps.stats.build_rep_stats_context`` does for reps:
a compact JSON-able dict the model synthesizes into prose. The committee
helpers it leans on (roster, name normalization, the bill/meeting buckets)
live in ``seattle_app.api_views`` and are imported lazily so this module stays
cheap to import and there's no import cycle.
"""
from __future__ import annotations

import hashlib
import json

# How much context to feed the model — enough to characterize focus + recent
# work without bloating the prompt.
_RECENT_MEETINGS = 8
_MAX_BILLS = 40
_OVERVIEW_CHARS = 400


def build_committee_stats_context(org) -> dict:
    """Structured snapshot for one committee: roster, recent meetings (with
    their LLM overview — the richest signal), and the bills it has handled."""
    from django.db.models import Max, Q

    from councilmatic_core.models import Bill, Event
    from seattle_app.api_views import (
        _committee_body_names,
        _committee_event_names,
        _committee_roster,
        _committee_vote_body_names,
        _normalise_status,
        _normalize_committee_name,
    )
    from seattle_app.models import CommitteeProfile, EventSummary

    norm = _normalize_committee_name(org.name)

    # Authoritative scope + meeting cadence scraped from the committee's
    # seattle.gov page (scrape_committee_info) — ground truth the model leads
    # with, rather than inferring the remit from bill titles. Absent until the
    # first scrape; the summary degrades to inference.
    profile = CommitteeProfile.objects.filter(organization_id=org.id).first()
    scope = profile.scope if profile else ""
    meeting_schedule = profile.meeting_schedule if profile else ""

    roster = _committee_roster(org)
    chair = next((m["name"] for m in roster if m["role"] == "Chair"), None)
    members = [{"name": m["name"], "role": m["role"]} for m in roster]

    # Recent meetings + their one-line overview (the rich signal; meetings
    # without a generated summary still appear, just with an empty overview).
    meetings: list[dict] = []
    event_names = _committee_event_names(norm)
    if event_names:
        recent = list(
            Event.objects.filter(name__in=event_names)
            .order_by("-start_date")[:_RECENT_MEETINGS]
        )
        overviews = {
            s.event_id: s.overview
            for s in EventSummary.objects.filter(event_id__in=[e.id for e in recent])
        }
        for e in recent:
            overview = (overviews.get(e.id) or "").strip()
            meetings.append({
                "name": e.name,
                "date": (e.start_date or "")[:10] if isinstance(e.start_date, str) else "",
                "overview": overview[:_OVERVIEW_CHARS],
            })

    # Bills handled — current body OR a committee vote event names it. Most
    # recent activity first. (Same union the committee detail page uses.)
    bills: list[dict] = []
    body_names = _committee_body_names(norm)
    vote_body_names = _committee_vote_body_names(norm)
    if body_names or vote_body_names:
        bill_filter = Q()
        if body_names:
            bill_filter |= Q(extras__MatterBodyName__in=body_names)
        if vote_body_names:
            bill_filter |= Q(votes__extras__event_body_name__in=vote_body_names)
        qs = (Bill.objects
              .filter(bill_filter)
              .annotate(_latest=Max("actions__date"))
              .order_by("-_latest")[:_MAX_BILLS])
        for b in qs:
            label, _variant = _normalise_status(b.extras.get("MatterStatusName", ""))
            bills.append({
                "identifier": b.identifier,
                "title": b.title,
                "status": label,
            })

    return {
        "name": org.name,
        "scope": scope,
        "meeting_schedule": meeting_schedule,
        "chair": chair,
        "members": members,
        "recent_meetings": meetings,
        "bills": bills,
    }


def committee_content_hash(ctx: dict) -> str:
    """SHA-256 over the *signal* fields of a committee context — roster,
    meeting overviews, and bills (identifier + status). ``summarize_committees``
    compares this against the stored ``content_hash`` to decide whether a
    committee's summary is stale; everything hashed here changes only when the
    committee's actual activity does, so unchanged committees are skipped."""
    signal = {
        "name": ctx.get("name", ""),
        "scope": ctx.get("scope", ""),
        "meeting_schedule": ctx.get("meeting_schedule", ""),
        "members": sorted((m["name"], m["role"]) for m in ctx.get("members", [])),
        "meetings": sorted(
            (m["name"], m["date"], m["overview"]) for m in ctx.get("recent_meetings", [])
        ),
        "bills": sorted((b["identifier"], b["status"]) for b in ctx.get("bills", [])),
    }
    blob = json.dumps(signal, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

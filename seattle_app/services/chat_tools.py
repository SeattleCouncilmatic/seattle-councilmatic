"""Tools the civic-Q&A chatbot can call.

Each public function below maps to a tool definition the model sees
(see ``chat_service.CHAT_TOOL_DEFINITIONS``). The model picks a tool and
arguments; the agent loop in ``chat_service.run_chat_turn`` dispatches
to the matching function here and feeds the JSON-serializable return
value back as a tool_result.

Design rules:

* All queries go through the Django ORM with parameterized filters. No
  raw SQL with user-supplied values (the per-user global rule against
  SQL injection).
* Return values are JSON-serializable dicts of plain strings, numbers,
  and lists — no model instances.
* Long text fields are truncated to ``_TEXT_BUDGET`` chars so a single
  tool call can't blow up the context window. The model gets a
  ``truncated: True`` flag when truncation happened so it can re-query
  with a tighter filter if needed.
* Unknown slugs / section numbers raise ``ChatToolNotFound``;
  agent loop converts it to a structured "not found" tool_result so
  the model can ask for clarification instead of hallucinating.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Max, Min, Q
from django.utils import timezone

from councilmatic_core.models import Bill, Event

from ..models import EventSummary, MunicipalCodeSection


# Max characters of free text we hand back per tool result. Roughly
# 1500 chars ≈ 400 tokens — small enough that 3-4 tool calls stay
# under ~2K tokens of tool-result context.
_TEXT_BUDGET = 1500

# Matches strings like "23.47A", "23.47A.014", "23" — same intent as
# api_views._CITATION_RE: detect when a user query is a section
# citation and prefix-match rather than running FTS.
_CITATION_RE = re.compile(r"^\d+(\.\d+[A-Z]?)*$")


# ---- Internal Councilmatic URL helpers ------------------------------------
#
# The chatbot answer-rendering markdown supports relative links, so
# `[CB 121153](/legislation/cb-121153)` resolves to the SPA's existing
# routes in both dev (localhost:5173) and prod (www.seattlecouncilmatic.org).
# Tools embed these URLs in their return payload so the model doesn't have to
# infer URL paths — every entity carries its own ``councilmatic_url`` field.
# Route shapes mirror frontend/src/App.jsx route definitions.

def _bill_url(slug: Optional[str]) -> Optional[str]:
    return f"/legislation/{slug}" if slug else None


def _event_url(slug: Optional[str]) -> Optional[str]:
    return f"/events/{slug}" if slug else None


def _rep_url(slug: Optional[str]) -> Optional[str]:
    return f"/reps/{slug}" if slug else None


def _smc_section_url(section_number: Optional[str]) -> Optional[str]:
    """SMC routes nest as /municode/<title>/<chapter>/<section> where each
    segment is one dot-separated piece of section_number (e.g. '23.42.040'
    → '/municode/23/42/040'). Section numbers that don't split into
    exactly 3 parts (titles or chapters, not sections) return None."""
    if not section_number:
        return None
    parts = section_number.split(".")
    if len(parts) != 3:
        return None
    return f"/municode/{parts[0]}/{parts[1]}/{parts[2]}"


class ChatToolError(Exception):
    """Base class for tool failures the agent loop should report
    back to the model as a structured error rather than aborting."""


class ChatToolNotFound(ChatToolError):
    """Specific slug / section number / id did not resolve."""


def _truncate(text: Optional[str], budget: int = _TEXT_BUDGET) -> tuple[str, bool]:
    """Returns (text, truncated_flag). Empty/None returns ('', False)."""
    if not text:
        return "", False
    if len(text) <= budget:
        return text, False
    return text[:budget].rstrip() + "…", True


def search_bills(
    query: str = "",
    sponsor: str = "",
    status: str = "",
    year: Optional[int] = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find bills matching a free-text query and optional filters.

    Mirrors the filtering shape of ``api_views.legislation_index`` but
    returns a compact tool-friendly payload.
    """
    limit = max(1, min(int(limit or 10), 20))
    bills = Bill.objects.all()

    if query:
        bills = bills.filter(Q(identifier__icontains=query) | Q(title__icontains=query))

    if sponsor:
        # icontains rather than iexact so a last-name-only query
        # ("Strauss") still matches the full name stored on the
        # sponsorship row ("Dan Strauss"). The user-facing legislation
        # index uses iexact because its sponsor filter is a dropdown of
        # canonical names; the chat tool receives free-form names from
        # the model and needs the flexibility.
        bills = bills.filter(sponsorships__name__icontains=sponsor).distinct()

    if status:
        bills = bills.filter(extras__MatterStatusName__iexact=status)

    bills = bills.annotate(
        latest_action_date=Max("actions__date"),
        earliest_action_date=Min("actions__date"),
    )

    if year is not None:
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            year_int = None
        if year_int and 1900 <= year_int <= 2100:
            bills = bills.filter(
                earliest_action_date__gte=f"{year_int}-01-01",
                earliest_action_date__lt=f"{year_int + 1}-01-01",
            )

    bills = (
        bills
        .prefetch_related("sponsorships", "actions", "llm_summary")
        .order_by("-latest_action_date")[:limit]
    )

    results = []
    for bill in bills:
        sponsorship = bill.sponsorships.first()
        sponsor_name = sponsorship.entity_name if sponsorship else None
        intro = bill.actions.order_by("date").first()
        intro_date = intro.date[:10] if intro and intro.date else None
        summary = getattr(bill, "llm_summary", None)
        summary_text, _ = _truncate(summary.summary, 400) if summary else ("", False)
        results.append({
            "identifier": bill.identifier,
            "slug": bill.slug,
            "councilmatic_url": _bill_url(bill.slug),
            "title": bill.title,
            "sponsor": sponsor_name,
            "status": bill.extras.get("MatterStatusName", ""),
            "classification": bill.extras.get("MatterTypeName", ""),
            "date_introduced": intro_date,
            "summary_excerpt": summary_text,
        })

    return {"count": len(results), "results": results}


def get_bill_detail(slug: str) -> dict[str, Any]:
    """Full detail for one bill by councilmatic slug.

    Includes the LegislationSummary fields (summary + impact_analysis +
    key_changes) when present — the bulk of the chatbot's grounding
    value for "what does this bill do / what's its impact" questions.
    """
    if not slug:
        raise ChatToolNotFound("slug is required")

    try:
        bill = (
            Bill.objects
            .prefetch_related(
                "actions",
                "sponsorships",
                "llm_summary__affected_sections",
            )
            .get(slug=slug)
        )
    except Bill.DoesNotExist as exc:
        raise ChatToolNotFound(f"no bill with slug={slug!r}") from exc

    sponsors = [
        {"name": s.entity_name, "primary": s.primary}
        for s in bill.sponsorships.order_by("-primary", "name")
        if s.entity_name
    ]

    actions = []
    seen_actions: set[tuple[str, str]] = set()
    for a in bill.actions.order_by("date", "description"):
        key = (a.date[:10] if a.date else "", a.description)
        if key in seen_actions:
            continue
        seen_actions.add(key)
        actions.append({
            "date": a.date[:10] if a.date else None,
            "description": a.description,
        })

    summary = getattr(bill, "llm_summary", None)
    llm_block: Optional[dict[str, Any]] = None
    truncated = False
    if summary is not None:
        sum_text, t1 = _truncate(summary.summary)
        impact_text, t2 = _truncate(summary.impact_analysis)
        truncated = t1 or t2
        llm_block = {
            "summary": sum_text,
            "impact_analysis": impact_text,
            "key_changes": summary.key_changes or [],
            "affected_sections": [
                {"section_number": s.section_number, "title": s.title}
                for s in summary.affected_sections.all().order_by("section_number")
            ],
        }

    # Public-facing Legistar URL — constructed from MatterId. Same
    # pattern as api_views.legislation_detail. We surface it so the
    # bot can point users at the canonical record (with committee
    # contact info + public-comment workflow) instead of inventing
    # email addresses or URLs for civic-engagement questions.
    matter_id = bill.extras.get("MatterId")
    legistar_url = (
        f"https://seattle.legistar.com/Gateway.aspx?M=L&ID={matter_id}"
        if matter_id else None
    )

    return {
        "identifier": bill.identifier,
        "slug": bill.slug,
        "councilmatic_url": _bill_url(bill.slug),
        "title": bill.title,
        "status": bill.extras.get("MatterStatusName", ""),
        "classification": bill.extras.get("MatterTypeName", ""),
        "committee": bill.extras.get("MatterBodyName", ""),
        "legistar_url": legistar_url,
        "sponsors": sponsors,
        "actions": actions,
        "llm_summary": llm_block,
        "truncated": truncated,
    }


def search_smc(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the Seattle Municipal Code by free-text query or citation.

    Uses the same FTS index as ``api_views.smc_search`` so behavior
    matches the user-facing search.
    """
    query = (query or "").strip()
    if not query:
        return {"count": 0, "results": [], "mode": "empty"}
    limit = max(1, min(int(limit or 5), 15))

    sections = MunicipalCodeSection.objects.all()
    is_citation = _CITATION_RE.match(query) is not None

    if is_citation:
        sections = sections.filter(section_number__istartswith=query).order_by("section_number")
        mode = "citation"
    else:
        ts = SearchQuery(query, search_type="websearch")
        sections = (
            sections
            .filter(search_vector=ts)
            .annotate(rank=SearchRank("search_vector", ts))
            .order_by("-rank", "section_number")
        )
        mode = "fts"

    sections = sections[:limit]

    results = []
    for s in sections:
        snippet, _ = _truncate(s.plain_summary or s.full_text, 600)
        results.append({
            "section_number": s.section_number,
            "title": s.title,
            "councilmatic_url": _smc_section_url(s.section_number),
            "snippet": snippet,
        })

    return {"count": len(results), "results": results, "mode": mode}


# Time-filter values for search_events. Mirror api_views._TIME_FILTER_VALUES.
_EVENT_TIME_VALUES = ("upcoming", "past", "all")

# Event-type labels we expose to the model. Match the buckets in
# api_views._classify_event (Hearing / Briefing / Council / Committee /
# Other). The model should pass one of these verbatim.
_EVENT_TYPE_VALUES = ("Hearing", "Briefing", "Council", "Committee", "Other")

# Matches "2026-05-22" — same shape as api_views._is_iso_date.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _classify_event_name(name: str) -> str:
    """Replicates api_views._classify_event (kept local so the chat tools
    module doesn't depend on a private helper across files)."""
    n = (name or "").lower().strip()
    if not n:
        return "Other"
    if "public hearing" in n:
        return "Hearing"
    if "briefing" in n:
        return "Briefing"
    if n.startswith("city council"):
        return "Council"
    if n.startswith("notice"):
        return "Other"
    return "Committee"


def search_events(
    query: str = "",
    time: str = "past",
    event_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Find council meetings (events) by name + time window + type.

    Default ``time='past'`` reflects the chat use case: most user
    questions are about meetings that have happened ("what did the
    Land Use committee discuss last week"), not future ones. Caller
    can pass ``time='upcoming'`` or ``'all'`` to broaden.
    """
    limit = max(1, min(int(limit or 10), 20))
    if time not in _EVENT_TIME_VALUES:
        time = "past"
    if event_type and event_type not in _EVENT_TYPE_VALUES:
        event_type = ""

    events = Event.objects.all()
    if query:
        events = events.filter(name__icontains=query)

    now = timezone.now()
    if time == "upcoming":
        events = events.filter(start_date__gte=now).order_by("start_date")
    elif time == "past":
        events = events.filter(start_date__lt=now).order_by("-start_date")
    else:
        events = events.order_by("-start_date")

    if date_from and _ISO_DATE_RE.match(date_from):
        events = events.filter(start_date__gte=date_from)
    if date_to and _ISO_DATE_RE.match(date_to):
        # See api_views.events_index — start_date is an ISO timestamp string,
        # so the upper bound needs padding to include same-day rows.
        events = events.filter(start_date__lte=date_to + "T99:99:99")

    # Type filter happens post-query because type is derived from name.
    candidates = list(events[:limit * 4])  # over-fetch then trim
    if event_type:
        candidates = [e for e in candidates if _classify_event_name(e.name) == event_type]
    candidates = candidates[:limit]

    results = []
    for ev in candidates:
        results.append({
            "name": ev.name,
            "slug": ev.slug,
            "councilmatic_url": _event_url(ev.slug),
            "type": _classify_event_name(ev.name),
            "start_date": (
                ev.start_date if isinstance(ev.start_date, str)
                else ev.start_date.isoformat() if ev.start_date else None
            ),
            "status": ev.status,
        })

    return {"count": len(results), "results": results, "time": time, "event_type": event_type}


def get_event_detail(slug: str) -> dict[str, Any]:
    """Full detail for one council meeting by slug.

    Returns the LLM-generated meeting overview + per-agenda-item
    summaries when present. This is the primary grounding source for
    "what happened at this meeting" questions.
    """
    if not slug:
        raise ChatToolNotFound("slug is required")
    try:
        event = Event.objects.prefetch_related("sources").get(slug=slug)
    except Event.DoesNotExist as exc:
        raise ChatToolNotFound(f"no event with slug={slug!r}") from exc

    # Optional EventSummary one-to-one.
    summary = EventSummary.objects.filter(event_id=event.id).first()
    summary_block: Optional[dict[str, Any]] = None
    truncated = False
    if summary is not None:
        overview, t1 = _truncate(summary.overview)
        # item_summaries is a JSONField list of {label, summary, start_seconds}.
        items = []
        for item in (summary.item_summaries or []):
            label = item.get("label", "")
            text, t2 = _truncate(item.get("summary", ""), 500)
            truncated = truncated or t2
            items.append({
                "label": label,
                "summary": text,
                "start_seconds": item.get("start_seconds"),
            })
        truncated = truncated or t1
        summary_block = {
            "overview": overview,
            "item_summaries": items,
        }

    # Public-facing Legistar URL — same pattern as api_views.event_detail.
    source = event.sources.first()
    legistar_url = source.url if source else None

    return {
        "name": event.name,
        "slug": event.slug,
        "councilmatic_url": _event_url(event.slug),
        "type": _classify_event_name(event.name),
        "start_date": (
            event.start_date if isinstance(event.start_date, str)
            else event.start_date.isoformat() if event.start_date else None
        ),
        "status": event.status,
        "description": (event.description or "").strip(),
        "legistar_url": legistar_url,
        "llm_summary": summary_block,
        "truncated": truncated,
    }


def get_rep_detail(slug: str) -> dict[str, Any]:
    """Full detail for a councilmember by slug or name fragment.

    Wraps ``reps.services.get_rep_by_slug`` and trims the response for
    the chat context budget — sponsored_bills is capped to the top 5,
    bio prose is truncated.

    Slug-resolution strategy:
      1. Try ``get_rep_by_slug(slug)`` — exact councilmatic slug match.
      2. If that returns None, fall back to a case-insensitive name
         substring match against currently-serving members. A single
         hit auto-resolves; multiple hits return a structured
         ``error='ambiguous'`` payload listing candidates so the
         model can ask the user which one they meant.
      3. Zero hits raises ChatToolNotFound.

    Only currently-serving members are surfaced; former members are
    deferred to a future iteration (would require an
    ``is_current=FALSE`` path through ``_query_current_council_members``
    and a labeling change in the response).
    """
    if not slug:
        raise ChatToolNotFound("slug is required")

    # Local import — reps app imports from seattle_app at module init,
    # so importing reps from seattle_app at module load creates a cycle.
    from reps.services import _query_current_council_members, get_rep_by_slug

    rep = get_rep_by_slug(slug)
    if rep is None:
        # Fallback: case-insensitive name fragment match. Wrapping the
        # parameter with % wildcards is part of the LIKE syntax and
        # the value still goes through psycopg2's %s binding, so the
        # raw query stays parameterized.
        matches = _query_current_council_members(
            extra_filter=" AND p.name ILIKE %s",
            params=[f"%{slug}%"],
        )
        if not matches:
            raise ChatToolNotFound(
                f"no current councilmember matches {slug!r} (former "
                f"members are not exposed by this tool)"
            )
        if len(matches) > 1:
            return {
                "error": "ambiguous",
                "detail": (
                    f"{len(matches)} current councilmembers matched "
                    f"{slug!r}. Ask the user which one they meant, then "
                    f"call get_rep_detail again with the chosen slug."
                ),
                "candidates": [
                    {"name": name, "slug": resolved_slug, "label": label}
                    for (name, resolved_slug, label, _person_id) in matches
                ],
            }
        # Exactly one match — use its real slug.
        _name, resolved_slug, _label, _person_id = matches[0]
        rep = get_rep_by_slug(resolved_slug)
        if rep is None:  # extremely unlikely race condition
            raise ChatToolNotFound(
                f"no current councilmember with slug={resolved_slug!r}"
            )

    # legislation_involvement is a list of row dicts (see
    # reps.services._get_legislation_involvement). Each row has
    # {'bill': {identifier, title, slug}, 'status': {label, variant},
    #  'sponsorship': 'primary'|'cosponsor'|None, ...}, sorted by
    # latest_action_date desc. For the chat use case ("what does this
    # rep work on"), filter to bills they actually sponsored and cap
    # to the top 5 most-recent.
    involvement = rep.get("legislation_involvement") or []
    sponsored_rows = [r for r in involvement if r.get("sponsorship")]
    bills_short = []
    for r in sponsored_rows[:5]:
        bill_dict = r.get("bill") or {}
        bill_slug = bill_dict.get("slug")
        bills_short.append({
            "identifier": bill_dict.get("identifier"),
            "title": bill_dict.get("title"),
            "slug": bill_slug,
            "councilmatic_url": _bill_url(bill_slug),
            "status": (r.get("status") or {}).get("label"),
            "sponsorship": r.get("sponsorship"),  # 'primary' | 'cosponsor'
            "latest_action_date": r.get("latest_action_date"),
        })

    summary = rep.get("summary") or {}
    summary_text, summary_truncated = _truncate(summary.get("text", ""))

    rep_slug = rep.get("slug")
    return {
        "name": rep.get("name"),
        "slug": rep_slug,
        "councilmatic_url": _rep_url(rep_slug),
        "label": rep.get("label"),  # district / seat label, e.g. "District 6"
        "voting_history": rep.get("voting_history"),
        "sponsored_bills": bills_short,
        "sponsored_bills_total": len(sponsored_rows),
        "llm_summary": summary_text,
        "truncated": summary_truncated,
    }


def list_councilmembers() -> dict[str, Any]:
    """Enumerate currently-serving Seattle City Councilmembers.

    Returns a compact list of all 9 current members with their name,
    slug, and seat label (e.g. 'District 6', 'Position 8'). Use this
    when the user asks about the council roster, who chairs a
    committee, or wants to identify a member by district. The model
    can pass the resulting slug to get_rep_detail for full detail.

    Committee chair info is in each member's rep_summary text, not in
    this compact listing — call get_rep_detail to see committee
    assignments.
    """
    # Local import to avoid the seattle_app ↔ reps init-time cycle.
    from reps.services import _query_current_council_members

    rows = _query_current_council_members()
    members = [
        {
            "name": name,
            "slug": slug,
            "councilmatic_url": _rep_url(slug),
            "label": label,
        }
        for (name, slug, label, _person_id) in rows
    ]
    return {"count": len(members), "members": members}


def get_bill_roll_call(slug: str) -> dict[str, Any]:
    """Vote breakdown for one bill across all its VoteEvents.

    For each vote event (committee votes + the final council vote
    when present), returns the date, body name, result, vote counts
    (yes/no/abstain/etc.), and per-member votes grouped by option.
    Empty list when the bill has no vote events — most bills
    introduced before Councilmatic's 548-day vote scrape window have
    no roll-call data.
    """
    if not slug:
        raise ChatToolNotFound("slug is required")
    try:
        bill = Bill.objects.prefetch_related(
            "votes__votes",
            "votes__counts",
        ).get(slug=slug)
    except Bill.DoesNotExist as exc:
        raise ChatToolNotFound(f"no bill with slug={slug!r}") from exc

    events = list(bill.votes.order_by("start_date"))
    out = []
    for ve in events:
        body = ((ve.extras or {}).get("event_body_name") or "").strip()
        votes_by_option: dict[str, list[str]] = {}
        for pv in ve.votes.all():
            votes_by_option.setdefault(pv.option, []).append(pv.voter_name or "")
        # Alphabetize within each option group for stable ordering.
        for opt in votes_by_option:
            votes_by_option[opt].sort(key=str.lower)
        counts = {opt: val for opt, val in ve.counts.values_list("option", "value")}
        out.append({
            "date": (ve.start_date or "")[:10],
            "body_name": body,
            "is_council_vote": body == "City Council",
            "motion": ve.motion_text or "",
            "result": ve.result,
            "counts": counts,
            "votes_by_option": votes_by_option,
        })

    return {
        "identifier": bill.identifier,
        "slug": bill.slug,
        "councilmatic_url": _bill_url(bill.slug),
        "vote_event_count": len(out),
        "vote_events": out,
    }


def search_event_summaries(query: str, limit: int = 5) -> dict[str, Any]:
    """Full-text-ish search across the LLM-generated meeting overviews.

    Useful for finding meetings whose **content** mentioned a topic,
    even when the topic isn't in the meeting name. EventSummary
    doesn't have a tsvector column the way MunicipalCodeSection does,
    so this falls back to case-insensitive substring match on
    ``overview``. Adequate for civic-Q&A keyword discovery; if this
    becomes a hotspot we can add a search_vector via migration later.

    Returns a compact list (event name, slug, start_date, snippet
    around the match) ordered by most-recent-meeting-first. Call
    get_event_detail next to read the full overview + per-item
    summaries.
    """
    query = (query or "").strip()
    if not query:
        return {"count": 0, "results": [], "query": query}
    limit = max(1, min(int(limit or 5), 15))

    rows = (
        EventSummary.objects
        .filter(overview__icontains=query)
        .select_related("event")
        .order_by("-event__start_date")[:limit]
    )

    results = []
    for s in rows:
        # Build a small snippet around the first hit so the model can
        # judge relevance without reading the whole overview.
        text = s.overview or ""
        idx = text.lower().find(query.lower())
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(text), idx + len(query) + 200)
            snippet_raw = text[start:end].strip()
            snippet = ("…" if start > 0 else "") + snippet_raw + ("…" if end < len(text) else "")
        else:
            snippet, _ = _truncate(text, 280)

        event = s.event
        results.append({
            "name": event.name,
            "slug": event.slug,
            "councilmatic_url": _event_url(event.slug),
            "type": _classify_event_name(event.name),
            "start_date": (
                event.start_date if isinstance(event.start_date, str)
                else event.start_date.isoformat() if event.start_date else None
            ),
            "snippet": snippet,
        })

    return {"count": len(results), "results": results, "query": query}

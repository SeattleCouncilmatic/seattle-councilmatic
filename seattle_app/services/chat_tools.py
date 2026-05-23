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

from councilmatic_core.models import Bill

from ..models import MunicipalCodeSection


# Max characters of free text we hand back per tool result. Roughly
# 1500 chars ≈ 400 tokens — small enough that 3-4 tool calls stay
# under ~2K tokens of tool-result context.
_TEXT_BUDGET = 1500

# Matches strings like "23.47A", "23.47A.014", "23" — same intent as
# api_views._CITATION_RE: detect when a user query is a section
# citation and prefix-match rather than running FTS.
_CITATION_RE = re.compile(r"^\d+(\.\d+[A-Z]?)*$")


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
        bills = bills.filter(sponsorships__name__iexact=sponsor).distinct()

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

    return {
        "identifier": bill.identifier,
        "slug": bill.slug,
        "title": bill.title,
        "status": bill.extras.get("MatterStatusName", ""),
        "classification": bill.extras.get("MatterTypeName", ""),
        "committee": bill.extras.get("MatterBodyName", ""),
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
            "snippet": snippet,
        })

    return {"count": len(results), "results": results, "mode": mode}

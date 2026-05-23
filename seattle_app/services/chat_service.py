"""Civic-Q&A chatbot: tool-use loop over Seattle Councilmatic data.

This is the orchestration layer above ``chat_tools``. Callers
(the smoke-test management command and the ``/api/chat/message``
endpoint) hand in a list of prior messages plus the user's new
question; ``run_chat_turn`` drives the Anthropic tool-use loop until
the model produces a final text answer (or hits the per-turn tool-call
budget) and returns a :class:`ChatTurnResult` with the answer + usage
metadata.

Architecture mirrors the existing batch pipelines in
``claude_service.py``: ephemeral prompt caching on the system block,
env-driven model selection, neutral civic-data persona. Differs in
two ways: (1) synchronous ``client.messages.create`` rather than the
Batches API — chat is interactive — and (2) the model is given tools
rather than a structured-output schema.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import anthropic
from django.conf import settings

from . import chat_tools
from .chat_tools import ChatToolError, ChatToolNotFound

logger = logging.getLogger(__name__)


CHAT_SYSTEM_PROMPT = (
    "You are the Seattle Councilmatic civic assistant. You help "
    "residents of Seattle understand their City Council: pending and "
    "passed legislation, meeting activity, the Seattle Municipal Code "
    "(SMC), council meetings, and councilmember portfolios.\n\n"
    "Tone:\n"
    "  - Neutral, factual, plain-English. You are a civic-data "
    "communicator, not an advocate. Describe what bills do and what "
    "councilmembers work on; do not speculate on motivations, "
    "ideology, party, or coalition.\n"
    "  - Concise. Default to short paragraphs and tight bullet points. "
    "A 'what does this bill do' question deserves 3-5 sentences, not "
    "a wall of text. A list of recent bills should be scannable, not "
    "exhaustive prose.\n"
    "  - Plain prose only. NO emoji icons in headers or bullets, no "
    "decorative dividers (---), no purely cosmetic markdown. Use plain "
    "section headings (##) and bullet lists where they help structure. "
    "The output renders in a chat panel that's adjacent to the rest of "
    "the site's plain-prose visual style.\n\n"
    "Citation rules — these are not optional:\n"
    "  - **Always cite bills by their identifier** in the form 'CB "
    "121153' (with the space, no dash, no slug). If you've looked up "
    "a bill, name it.\n"
    "  - **Always name the sponsor** when discussing a specific bill, "
    "drawn from the sponsors[].name field of get_bill_detail or the "
    "sponsor field of search_bills. Use the primary sponsor; if "
    "multiple primary sponsors, list them all. If the sponsor field is "
    "empty in the tool result, write 'sponsor unlisted' rather than "
    "guessing.\n"
    "  - **Always include the relevant date** when discussing a "
    "specific bill: passage date for bills that have passed (last "
    "action with description containing 'Passed' or 'Adopted' or "
    "'Signed'), introduction date otherwise. Date format: 'Mar 2026' "
    "or 'March 2026' (month + year is enough granularity).\n"
    "  - **Cite SMC sections by section number** (e.g. 'SMC 23.42.040') "
    "rather than topic descriptions alone.\n"
    "  - **Preserve concrete numbers** from impact_analysis and "
    "key_changes verbatim — dollar amounts, percentages, AMI bands, "
    "statute citations like 'HB 1337' or 'RCW 59.18.700', sunset "
    "dates. These are the load-bearing facts; do not abstract them "
    "away.\n\n"
    "Grounding:\n"
    "  - Always prefer tool calls over your own knowledge. The Seattle "
    "Councilmatic database is the authoritative source for what bills "
    "have been introduced and what the SMC currently says. If you "
    "haven't called a tool to confirm a fact, you don't know it.\n"
    "  - If a tool returns no results, say so directly. Do not invent "
    "bill numbers, sponsor names, SMC sections, dates, or dollar "
    "amounts.\n"
    "  - 'Pros and cons', 'tradeoffs', or 'impact' questions: work "
    "to identify BOTH benefits and tensions/concerns, even when the "
    "source data doesn't explicitly label them as 'pros' or 'cons'. "
    "Most legislation has structural tradeoffs you can surface by "
    "reading the bill carefully — that's analysis, not editorializing. "
    "Look for structural cues:\n"
    "      • Administrative overhead / cost deductions that reduce "
    "net benefit (cap percentages, set-aside amounts, loan "
    "repayments taken off the top before transfers).\n"
    "      • Time-bounded provisions (sunset dates, auto-renewing "
    "terms that constrain future councils, exemption windows that "
    "expire and revert to market terms).\n"
    "      • Implementation gaps or delays (a tax effective in year "
    "X but with first collections in year X+1; a program with a "
    "60- or 90-day review clock).\n"
    "      • Risk-management provisions that imply acknowledged "
    "exposure (lawsuit-notification clauses, multi-tier dispute "
    "resolution paths, audit rights).\n"
    "      • Scope boundaries — what the bill does NOT address "
    "(governance over how money is spent downstream; tenant "
    "protections that are or aren't included; concerns left to a "
    "future bill).\n"
    "      • Trade-offs between competing priorities (flexibility "
    "vs. predictability; revenue capture vs. administrative cost; "
    "tenant protection vs. landlord operating margin).\n"
    "    Frame inferred tensions as 'potential' or 'possible' "
    "concerns, NOT as advocacy or stakeholder ventriloquism. Do not "
    "invent opposition voices ('critics argue...', 'opponents say...') "
    "unless you found them in actual event-summary public-comment "
    "themes. The goal is to surface design tradeoffs visible in the "
    "bill text, not to predict how political actors will react. If "
    "after careful structural review you genuinely cannot identify "
    "any meaningful tensions, say so explicitly rather than padding "
    "with weak boilerplate.\n\n"
    "Workflow:\n"
    "  - For a question about a specific bill (\"what does CB 121153 "
    "do?\"), call get_bill_detail with the slug if you have it, or "
    "search_bills first to find it.\n"
    "  - For a topic question (\"recent housing bills\"), call "
    "search_bills with the topic as the query. If the user wants depth "
    "on any one of them, follow up with get_bill_detail.\n"
    "  - For a comparison question (\"how do bills X and Y differ?\"), "
    "call get_bill_detail on each of the bills, then synthesize. "
    "Structure the answer as parallel sections so the comparison is "
    "easy to scan.\n"
    "  - For a council-meeting question (\"what happened at last "
    "week's Land Use meeting?\"), call search_events to find the "
    "meeting, then get_event_detail for the agenda + summary.\n"
    "  - For a councilmember question (\"what does Strauss work on?\"), "
    "call get_rep_detail.\n"
    "  - For a legal/code question (\"what does the noise ordinance "
    "say?\"), call search_smc.\n"
    "  - Don't loop on the same tool with similar arguments. If a "
    "search returns nothing useful, tell the user and ask for "
    "clarification rather than fishing.\n"
)


# Tool schemas — JSON Schemas Anthropic exposes to the model. Names
# and parameters MUST match the public functions in ``chat_tools``.
CHAT_TOOL_DEFINITIONS = [
    {
        "name": "search_bills",
        "description": (
            "Find Seattle City Council bills matching a free-text query "
            "and optional filters. Returns a compact list (identifier, "
            "slug, title, sponsor, status, classification, intro date, "
            "summary excerpt). Use this when the user asks about a topic "
            "(housing, transportation, surveillance) or names a sponsor "
            "or status. Call get_bill_detail after this to get the full "
            "summary + impact analysis for any bill you want to discuss "
            "in depth."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search against bill identifier and title. Pass empty string to skip text matching.",
                },
                "sponsor": {
                    "type": "string",
                    "description": "Exact councilmember name (case-insensitive) to filter sponsorships by. Pass empty string to skip.",
                },
                "status": {
                    "type": "string",
                    "description": "Bill status (Passed, In Committee, Introduced, etc.). Pass empty string to skip.",
                },
                "year": {
                    "type": "integer",
                    "description": "Restrict to bills first introduced in this calendar year (e.g. 2025). Omit to skip.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Default 10, max 20.",
                },
            },
        },
    },
    {
        "name": "get_bill_detail",
        "description": (
            "Full detail for one bill by its councilmatic slug. Returns "
            "the LLM-generated summary, impact analysis, and structured "
            "key_changes when available, plus sponsors, action history, "
            "and affected SMC sections. Use this when the user asks "
            "about a specific bill in depth or wants pros/cons / impact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Councilmatic slug for the bill (e.g. 'cb-120123'). Obtain from search_bills results.",
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "search_smc",
        "description": (
            "Search the Seattle Municipal Code by free-text query or "
            "citation prefix (e.g. '23.47A'). Returns up to 5 matching "
            "sections with the LLM-generated plain_summary excerpt. Use "
            "this for legal/code questions ('what does the noise "
            "ordinance say?', 'is there a rule about ADUs?') or when a "
            "bill references a section the user wants explained."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text query or citation prefix (e.g. '23.42' or 'short-term rental').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max sections to return. Default 5, max 15.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_events",
        "description": (
            "Find Seattle City Council meetings (Full Council, "
            "committee meetings, public hearings, briefings) by name "
            "substring + time window + type. Defaults to past meetings; "
            "pass time='upcoming' for future meetings. Returns a "
            "compact list (name, slug, type, start_date, status). Call "
            "get_event_detail next to read the agenda + LLM-generated "
            "meeting summary for any specific meeting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring match against the meeting name (e.g. 'Land Use', 'Transportation'). Empty string skips name filtering.",
                },
                "time": {
                    "type": "string",
                    "enum": ["upcoming", "past", "all"],
                    "description": "Window: past (default), upcoming, or all.",
                },
                "event_type": {
                    "type": "string",
                    "enum": ["Hearing", "Briefing", "Council", "Committee", "Other"],
                    "description": "Restrict to one event type. Omit to include all.",
                },
                "date_from": {
                    "type": "string",
                    "description": "ISO date 'YYYY-MM-DD' lower bound on start_date. Omit to skip.",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO date 'YYYY-MM-DD' upper bound on start_date (inclusive). Omit to skip.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max meetings to return. Default 10, max 20.",
                },
            },
        },
    },
    {
        "name": "get_event_detail",
        "description": (
            "Full detail for one council meeting by slug. Returns the "
            "LLM-generated meeting overview + per-agenda-item summaries "
            "when available — primary grounding source for 'what "
            "happened at this meeting' questions. Use this after "
            "search_events to dig into a specific meeting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Councilmatic slug for the event. Obtain from search_events results.",
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "get_rep_detail",
        "description": (
            "Profile for a current Seattle councilmember by their "
            "councilmatic slug OR name fragment. Returns the "
            "LLM-generated rep summary, lifetime voting breakdown "
            "(yes/no/abstain counts), seat label (e.g. 'District 6' "
            "or 'Position 8'), and up to 5 of their most-recently-"
            "actioned sponsored bills. Use this for questions like "
            "'what does Strauss work on?' or 'what bills has Foster "
            "sponsored?'. Only currently-serving members are exposed. "
            "If multiple members match a fragment, returns "
            "error='ambiguous' with a candidates list — ask the user "
            "which one they meant and call again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Councilmatic slug OR a case-insensitive name "
                        "fragment. Try the most natural form the user "
                        "gave you ('Strauss', 'Foster', 'dan-strauss'). "
                        "The tool will exact-match the slug first, then "
                        "fall back to a name search."
                    ),
                },
            },
            "required": ["slug"],
        },
    },
]


# Per-model list pricing in USD per 1M tokens. Used to estimate
# per-turn cost for the daily $ cap and ChatUsageLog. Authoritative
# numbers come from Anthropic's published price page; bump these
# alongside model upgrades. Keys are the model names exactly as they
# arrive in ``response.model`` from the API.
_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    # Haiku 4.5 — interactive default.
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "cached_input": 0.10,
        "output": 5.00,
    },
    "claude-haiku-4-5": {  # alias if the API echoes the unversioned name
        "input": 1.00,
        "cached_input": 0.10,
        "output": 5.00,
    },
    # Sonnet 4.6 — escalation target.
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cached_input": 0.30,
        "output": 15.00,
    },
    # Opus 4.7 — escalation target for highest-quality runs.
    "claude-opus-4-7": {
        "input": 15.00,
        "cached_input": 1.50,
        "output": 75.00,
    },
}

# Fallback pricing for unknown models. Conservative (assumes Sonnet
# tier) so the daily cap binds even if a new model name slips through.
_PRICING_FALLBACK = {"input": 3.00, "cached_input": 0.30, "output": 15.00}


# Trigger words that escalate the turn to the synthesis model. Anchored
# on word boundaries so "different" matches but "differential" doesn't.
# A/B testing (2026-05-22) showed Haiku produces tight, accurate
# listings but drops factual depth (sponsors, dates, sunset clauses,
# tenant protections) on multi-bill comparison questions. The
# escalation pays the ~4× Sonnet premium only on those.
_SYNTHESIS_PATTERN = re.compile(
    r"\b("
    r"compare|comparison|comparing|"
    r"versus|\bvs\b|"
    r"differ|difference|differences|different|"
    r"tradeoff|tradeoffs|trade-off|trade-offs|"
    r"contrast|contrasts|contrasting|"
    r"pros\s+and\s+cons|pros\s*/\s*cons|"
    r"weigh"
    r")\b",
    re.IGNORECASE,
)


def _is_synthesis_query(message: str) -> bool:
    """Whether ``message`` looks like a multi-source synthesis question.

    Hit rate is intentionally biased toward false positives — paying
    the ~4× Sonnet premium on a borderline-misclassified query is
    cheap relative to the daily cap, while under-escalating means
    users see thinner answers on the questions where depth matters
    most.
    """
    if not message:
        return False
    return _SYNTHESIS_PATTERN.search(message) is not None


def pick_model_for_message(
    message: str,
    *,
    default_model: Optional[str] = None,
    synthesis_model: Optional[str] = None,
) -> tuple[str, str]:
    """Choose which Claude model to use for one chatbot turn.

    Returns ``(model_name, reason)``. ``reason`` is 'synthesis' when
    escalation fired, 'default' otherwise. Caller can show this in a
    smoke-test log or persist it on ChatUsageLog if useful later.
    """
    default_model = default_model or settings.CLAUDE_CHAT_MODEL
    synthesis_model = synthesis_model or settings.CLAUDE_CHAT_SYNTHESIS_MODEL
    if synthesis_model and synthesis_model != default_model and _is_synthesis_query(message):
        return synthesis_model, "synthesis"
    return default_model, "default"


@dataclass
class ChatTurnResult:
    """What ``run_chat_turn`` returns to its caller."""

    answer_text: str
    model_used: str
    model_reason: str = "default"  # "default" or "synthesis"
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    estimated_cost_usd: Decimal = Decimal("0")
    error: Optional[str] = None


def hash_ip(ip: Optional[str]) -> str:
    """SHA-256 of ip + the Django SECRET_KEY salt. Empty IP → empty hash."""
    if not ip:
        return ""
    salt = (getattr(settings, "SECRET_KEY", "") or "").encode("utf-8")
    return hashlib.sha256(ip.encode("utf-8") + b"|" + salt).hexdigest()


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Cost estimate for a single turn using list prices for ``model``."""
    p = _PRICING_USD_PER_MTOK.get(model, _PRICING_FALLBACK)
    cost = (
        input_tokens * p["input"]
        + cached_input_tokens * p["cached_input"]
        + output_tokens * p["output"]
    ) / 1_000_000.0
    return Decimal(f"{cost:.6f}")


def _dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    """Map a tool name from the model to the implementation in chat_tools.

    Returns whatever the implementation returns (JSON-serializable).
    Tool errors are converted to dicts with an ``error`` key so the
    model can read the failure and react.
    """
    impl = {
        "search_bills": chat_tools.search_bills,
        "get_bill_detail": chat_tools.get_bill_detail,
        "search_smc": chat_tools.search_smc,
        "search_events": chat_tools.search_events,
        "get_event_detail": chat_tools.get_event_detail,
        "get_rep_detail": chat_tools.get_rep_detail,
    }.get(name)
    if impl is None:
        return {"error": f"unknown tool: {name!r}"}
    try:
        return impl(**(args or {}))
    except ChatToolNotFound as exc:
        return {"error": "not_found", "detail": str(exc)}
    except ChatToolError as exc:
        return {"error": "tool_error", "detail": str(exc)}
    except TypeError as exc:
        # bad argument shape from the model
        return {"error": "bad_arguments", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - we report back to model
        logger.exception("Unexpected error in chat tool %s", name)
        return {"error": "internal_error", "detail": str(exc)}


def run_chat_turn(
    *,
    history: list[dict[str, Any]],
    user_message: str,
    model: Optional[str] = None,
    max_tool_calls: Optional[int] = None,
    max_output_tokens: Optional[int] = None,
    client: Optional[anthropic.Anthropic] = None,
) -> ChatTurnResult:
    """Run one user turn through the tool-use loop.

    ``history`` is the prior conversation in Anthropic message format
    (``{role: 'user'|'assistant', content: ...}``). ``user_message`` is
    the new question to append. Returns a ChatTurnResult with the
    assistant's final text answer and accumulated usage.

    The loop terminates when the model returns ``stop_reason ==
    'end_turn'`` (final answer ready) or when we hit
    ``max_tool_calls``. Hitting the cap appends a synthetic "max
    tool calls reached" tool result so the model can wrap up with
    whatever context it has.
    """
    if max_tool_calls is None:
        max_tool_calls = settings.CHAT_MAX_TOOL_CALLS_PER_TURN
    if model is None:
        model, model_reason = pick_model_for_message(user_message)
    else:
        model_reason = "override"
    if max_output_tokens is None:
        # Synthesis answers (comparisons, pros/cons, multi-bill
        # explanations) need more headroom — empirical observation
        # is that they bump against the cap at ~1024. Default the
        # synthesis turns to 2048 and default everything else to 1024.
        max_output_tokens = 2048 if model_reason == "synthesis" else 1024
    if client is None:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build the running message list. We mutate this through the loop;
    # the caller's `history` is not modified in place.
    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": user_message}
    ]

    system_block = [{
        "type": "text",
        "text": CHAT_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    tool_calls_log: list[dict[str, Any]] = []
    input_tokens_total = 0
    cached_input_total = 0
    output_tokens_total = 0
    stop_reason = ""
    final_text = ""

    for _step in range(max_tool_calls + 1):
        response = client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system_block,
            tools=CHAT_TOOL_DEFINITIONS,
            messages=messages,
        )

        usage = response.usage
        input_tokens_total += int(getattr(usage, "input_tokens", 0) or 0)
        cached_input_total += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        output_tokens_total += int(getattr(usage, "output_tokens", 0) or 0)
        stop_reason = response.stop_reason or ""
        model_used = response.model or model

        # Collect text blocks for a potential final answer; collect
        # tool_use blocks for dispatch.
        text_parts: list[str] = []
        tool_uses: list[Any] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            # Final answer.
            final_text = "\n".join(t for t in text_parts if t).strip()
            break

        # Otherwise: model wants to use one or more tools. Append the
        # assistant turn (with the tool_use blocks) and a user turn
        # carrying tool_result blocks for each.
        assistant_content = [
            {"type": "text", "text": b.text} if getattr(b, "type", None) == "text"
            else {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
            for b in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})

        tool_results_content: list[dict[str, Any]] = []
        for tu in tool_uses:
            result = _dispatch_tool(tu.name, tu.input or {})
            tool_calls_log.append({
                "name": tu.name,
                "input": tu.input,
                "result_keys": list(result.keys()) if isinstance(result, dict) else None,
                "error": result.get("error") if isinstance(result, dict) else None,
            })
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": _json_str(result),
            })
        messages.append({"role": "user", "content": tool_results_content})

        if len(tool_calls_log) >= max_tool_calls:
            # One last call to let the model wrap up with what it has.
            response = client.messages.create(
                model=model,
                max_tokens=max_output_tokens,
                system=system_block,
                tools=CHAT_TOOL_DEFINITIONS,
                messages=messages + [{
                    "role": "user",
                    "content": (
                        "You've used your tool-call budget for this turn. "
                        "Answer the user's question with the information "
                        "you've already gathered. If you genuinely cannot "
                        "answer, tell them what's missing."
                    ),
                }],
            )
            usage = response.usage
            input_tokens_total += int(getattr(usage, "input_tokens", 0) or 0)
            cached_input_total += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            output_tokens_total += int(getattr(usage, "output_tokens", 0) or 0)
            stop_reason = response.stop_reason or "max_tool_calls"
            final_text = "\n".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            ).strip()
            break
    else:  # pragma: no cover - defensive; loop range covers all branches
        stop_reason = stop_reason or "loop_exhausted"

    cost = estimate_cost_usd(
        model=model,
        input_tokens=input_tokens_total,
        cached_input_tokens=cached_input_total,
        output_tokens=output_tokens_total,
    )

    return ChatTurnResult(
        answer_text=final_text,
        model_used=model,
        model_reason=model_reason,
        input_tokens=input_tokens_total,
        cached_input_tokens=cached_input_total,
        output_tokens=output_tokens_total,
        tool_calls=tool_calls_log,
        stop_reason=stop_reason,
        estimated_cost_usd=cost,
    )


def _json_str(value: Any) -> str:
    """Tool results must be strings in tool_result.content blocks.

    Anthropic accepts a string or a list of typed blocks; we pass JSON
    strings so the model can read structured data.
    """
    import json as _json
    try:
        return _json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialize tool result: %s", exc)
        return _json.dumps({"error": "serialization_failed", "detail": str(exc)})

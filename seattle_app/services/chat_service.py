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
    "  - **Always link to Councilmatic pages** when you mention a "
    "specific bill, meeting, councilmember, or SMC section. Every "
    "tool result that names one of these entities carries a "
    "`councilmatic_url` field — render the entity as a markdown link "
    "to that URL: `[CB 121153](/legislation/cb-121153)`, "
    "`[Land Use Committee meeting on 2026-05-11](/events/land-use-and-sustainability-committee-2026-05-11-21-00-00)`, "
    "`[Councilmember Strauss](/reps/dan-strauss)`, "
    "`[SMC 23.42.040](/municode/23/42/040)`. Relative URLs are "
    "correct — they resolve to the SPA's existing routes. Do this "
    "on the first mention of an entity; subsequent mentions in the "
    "same answer can stay plain text.\n"
    "  - **NEVER construct or infer a councilmatic_url yourself.** "
    "Only use URLs that came back in a tool result this turn. If "
    "you want to link to something but no tool call returned its "
    "URL, do one of two things: (a) call the relevant tool to "
    "get a real slug, or (b) mention the entity as plain text "
    "without a link. Specifically: there is NO standalone "
    "'committee' entity in Councilmatic — only date-stamped "
    "meeting instances. Do NOT invent URLs like "
    "`/events/land-use-committee` or `/events/<committee-name>`; "
    "if you want to link to the Land Use committee's recent "
    "activity, call search_events to get a specific meeting URL "
    "and link to that. The same applies to any entity: no real "
    "URL in a tool result → no link.\n"
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
    "Civic engagement / procedural questions ('how do I provide "
    "public comment?', 'when does the committee meet?', 'who do I "
    "contact about this bill?'):\n"
    "  - These are HIGH-RISK for hallucination because there's no "
    "tool that returns canonical contact info. Do NOT invent email "
    "addresses, phone numbers, web form URLs, or office addresses. "
    "If you don't have a real URL from a tool result, say 'check "
    "[the canonical source]' without inventing the URL.\n"
    "  - Always call get_bill_detail (or get_event_detail) first — "
    "the response includes a `legistar_url` field with the canonical "
    "Legistar page for that bill / meeting. THAT page has the "
    "committee's contact info, the public-comment process, and the "
    "meeting calendar. Linking to it is honest; inventing alternative "
    "addresses is not.\n"
    "  - General civic-engagement advice you may safely give without "
    "a tool: the bill's sponsoring committee (from "
    "get_bill_detail.committee), the bill's primary sponsor's office "
    "(from get_bill_detail.sponsors), the option of in-person or "
    "written testimony at committee meetings, and the Legistar URL "
    "when you have one. Anything more specific (email addresses, "
    "phone numbers, public-comment forms) needs to come from a tool "
    "result.\n\n"
    "Workflow:\n"
    "  - For a question about a specific bill (\"what does CB 121153 "
    "do?\"), call get_bill_detail directly. The slug is mechanically "
    "derivable from the identifier: 'CB 121153' → 'cb-121153' "
    "(lowercase, space replaced with hyphen). Skip search_bills "
    "unless you genuinely don't know the identifier.\n"
    "  - For a topic question (\"recent housing bills\"), call "
    "search_bills with the topic as the query. If the user wants depth "
    "on any one of them, follow up with get_bill_detail.\n"
    "  - For a comparison question (\"how do bills X and Y differ?\"), "
    "call get_bill_detail on each of the bills, then synthesize. "
    "Structure the answer as parallel sections so the comparison is "
    "easy to scan.\n"
    "  - For a vote-breakdown question (\"who voted yes/no on CB X?\", "
    "\"was the vote unanimous?\"), call get_bill_roll_call.\n"
    "  - For 'what is the council currently considering / debating / "
    "working on' questions, check BOTH search_bills(status='In "
    "Committee') AND search_events(time='upcoming') — these are "
    "complementary views (pending legislation + upcoming meeting "
    "agendas). Report both.\n"
    "  - For a council-meeting question (\"what happened at last "
    "week's Land Use meeting?\"), call search_events to find the "
    "meeting, then get_event_detail for the agenda + summary. If the "
    "user asks about meetings that *discussed* a topic (not just "
    "meetings whose NAME contains it), use search_event_summaries "
    "instead — it searches meeting CONTENT.\n"
    "  - For a 'who's on the council' / committee-roster question, "
    "call list_councilmembers first. Drill into any member with "
    "get_rep_detail.\n"
    "  - For a councilmember question (\"what does Strauss work on?\"), "
    "call get_rep_detail.\n"
    "  - For a legal/code question (\"what does the noise ordinance "
    "say?\"), call search_smc.\n"
    "  - Don't loop on the same tool with similar arguments. If a "
    "search returns nothing useful, tell the user and ask for "
    "clarification rather than fishing.\n\n"
    "Scope and refusal:\n"
    "  - You only know about Seattle municipal data through these "
    "tools. For questions about other cities, state/federal "
    "legislation, predictions about future votes or political "
    "outcomes, or interpretation of legal documents not in the "
    "SMC, say so clearly and don't guess.\n"
    "  - 'When will X be voted on?' / 'will this pass?' / 'how will "
    "councilmember Y vote?' — refuse cleanly. You don't have vote "
    "calendars and you don't predict political outcomes. State the "
    "bill's current status (from get_bill_detail) and direct the "
    "user to the Legistar page for upcoming activity.\n"
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
            "key_changes when available, plus sponsors (each with a "
            "councilmatic_url linking to their /reps/<slug> profile "
            "page where one exists — link both the bill and each "
            "sponsor in your answer), the Legistar URL, action history, "
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
    {
        "name": "list_councilmembers",
        "description": (
            "Enumerate all 9 currently-serving Seattle City "
            "Councilmembers. Returns name, slug, and seat label "
            "(District 1-7 or Position 8-9 at-large) for each. Use "
            "this for questions like 'who's on the council?', 'who "
            "are the at-large members?', 'who represents District 6?'. "
            "Combine with get_rep_detail to dig into any specific "
            "member's portfolio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_bill_roll_call",
        "description": (
            "Full vote breakdown for one bill across all its vote "
            "events (committee votes + final council vote when "
            "present). Returns each event's date, body name, motion "
            "text, result, yes/no/abstain/etc. counts, and per-"
            "councilmember votes grouped by option. Use this for "
            "questions like 'how did each councilmember vote on CB "
            "121153?', 'who voted no on the MFTE renewal?', 'was the "
            "vote unanimous?'. Empty when the bill has no recorded "
            "votes (typical for bills introduced before Councilmatic's "
            "scrape window or still in committee)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Councilmatic slug for the bill (e.g. "
                        "'cb-121153'). For a 'CB <number>' identifier, "
                        "the slug is 'cb-<number>' lowercased."
                    ),
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "search_event_summaries",
        "description": (
            "Find council meetings whose LLM-generated overview "
            "mentions a topic. Different from search_events — that "
            "searches meeting NAMES (e.g. 'Land Use'); this searches "
            "the CONTENT of what was discussed at meetings (e.g. "
            "'surveillance', 'data centers', 'tree canopy'). Use this "
            "when the user asks about meetings that discussed a topic "
            "even when the topic isn't in the committee name. Returns "
            "matching meetings with a snippet around the keyword "
            "match; call get_event_detail next to read the full "
            "summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic / keyword to find in meeting overviews.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max meetings to return. Default 5, max 15.",
                },
            },
            "required": ["query"],
        },
    },
]


# Per-model list pricing in USD per 1M tokens. Used to estimate
# per-turn cost for the daily $ cap and ChatUsageLog. Authoritative
# numbers come from Anthropic's published price page; bump these
# alongside model upgrades. Keys are the model names exactly as they
# arrive in ``response.model`` from the API.
#
# Sonnet/Opus stay in the table because operators can override
# CLAUDE_CHAT_MODEL to either of them via env var (or pass --model to
# the smoke test), and the cost estimator needs accurate per-model
# pricing in either case. The chatbot defaults to Haiku because A/B
# testing (2026-05-22, post-prompt-tuning) showed Haiku produces
# Sonnet-equivalent output on listing, comparison, and pros/cons
# questions at ~half the cost — the synthesis escalation we briefly
# carried was a workaround for an under-engaged-Haiku prompt, not a
# capability gap.
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
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cached_input": 0.30,
        "output": 15.00,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "cached_input": 1.50,
        "output": 75.00,
    },
}

# Fallback pricing for unknown models. Conservative (assumes Sonnet
# tier) so the daily cap binds even if a new model name slips through.
_PRICING_FALLBACK = {"input": 3.00, "cached_input": 0.30, "output": 15.00}


@dataclass
class ChatTurnResult:
    """What ``run_chat_turn`` returns to its caller."""

    answer_text: str
    model_used: str
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
        "list_councilmembers": chat_tools.list_councilmembers,
        "get_bill_roll_call": chat_tools.get_bill_roll_call,
        "search_event_summaries": chat_tools.search_event_summaries,
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
    max_output_tokens: int = 2048,
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
        model = settings.CLAUDE_CHAT_MODEL
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

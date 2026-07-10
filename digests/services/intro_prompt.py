"""Prompt + request construction for the digest intro batch (Phase 3, #238).

PII rule (plan §security 11): the request sent to Anthropic is built ONLY
from the whitelisted fields assembled here — issue-area tags, councilmember
names, the district label, bill identifiers, and the matched items' public
content. Never the subscriber's email, and the ``custom_id`` is the opaque
internal integer id. ``test_intro_prompt`` asserts no email-shaped string
survives into the serialized request body.
"""
import json

from django.conf import settings

from digests.services.llm_schema import compose_schema

# One short paragraph in, one short paragraph out.
MAX_TOKENS = 300

INTRO_SYSTEM_PROMPT = """\
You write the opening paragraph of a personalized email digest for Seattle \
Councilmatic, a nonpartisan civic-information site covering the Seattle City \
Council.

You receive JSON describing one subscriber's civic interests (issue areas, \
followed councilmembers, council district, followed bills) and the digest \
items matched to those interests this period — bills with recent council \
actions and committee-meeting recaps, each carrying the reason it matched \
and a short factual summary.

Return JSON with one key, "intro": a single paragraph of 2-4 sentences, \
under 90 words, that:
- Leads with the most significant or timely item for THIS subscriber and \
connects it to their stated interests.
- Sketches the rest of the digest briefly (e.g. "plus two transportation \
bills and a Public Safety committee recap").
- Refers to bills by identifier (e.g. "CB 121205") when naming them.
- Uses plain, neutral, nonpartisan language: no hype, no advocacy, no \
speculation about motives or outcomes.
- States only facts present in the input. Never invent bill contents, \
votes, dates, or outcomes.
- Contains no greeting, no sign-off, and no mention of email mechanics \
(subscriptions, links, unsubscribing) — the template handles all of that.\
"""


def build_intro_request(subscriber_id: int, prefs, items: list[dict],
                        cadence: str, model: str) -> dict:
    """One Anthropic Batch request for one subscriber's digest intro."""
    payload = {
        "cadence": cadence,
        "subscriber_interests": _prefs_context(prefs),
        "items": [_item_context(i) for i in items],
    }
    return {
        # Opaque internal id — matches Anthropic's ^[a-zA-Z0-9_-]{1,64}$
        # and carries no meaning outside our system.
        "custom_id": f"sub-{subscriber_id}",
        "params": {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": [{
                "type": "text",
                "text": INTRO_SYSTEM_PROMPT,
                # Cached across the cohort inside each 5-minute window —
                # same idiom as summarize_legislation.
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": [{
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            }],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": compose_schema(include_blurbs=False),
                },
            },
            # No `thinking`: the digest model is Haiku (which rejects the
            # parameter), and a 90-word intro doesn't warrant it anyway.
        },
    }


def _prefs_context(prefs) -> dict:
    """Whitelisted, PII-free view of the subscriber's preferences."""
    return {
        "issue_areas": prefs.issue_areas,
        "followed_councilmembers": sorted(
            prefs.followed_reps.values_list("name", flat=True)
        ),
        "district": prefs.district.name if prefs.district else None,
        "followed_bills": sorted(
            prefs.followed_bills.values_list("identifier", flat=True)
        ),
    }


def _item_context(item: dict) -> dict:
    return {
        # Stable id the Phase 5 blurb schema keys on.
        "item_id": f"{item['type']}-{item['id']}",
        "type": item["type"],
        "identifier": item["identifier"],
        "title": item["short_title"],
        "date": item["date"],
        "latest_action": item["latest_action"],
        "matched_because": item["reasons"],
        "summary": item["summary"],
    }


def digest_model() -> str:
    return settings.CLAUDE_DIGEST_MODEL

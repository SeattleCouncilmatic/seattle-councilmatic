"""Output schema for the digest-compose LLM call (Phase 3, #238).

One helper, one kwarg: ``compose_schema(include_blurbs=False)`` is the v1
``{intro}`` shape; flipping the kwarg is the entire schema side of the
Phase 5 per-item-blurbs expansion (the request payload already carries
stable ``item_id``s, and ``DigestSend.llm_payload`` is JSONB — no
migration, no rewrite).
"""


def compose_schema(include_blurbs: bool = False) -> dict:
    properties = {
        "intro": {
            "type": "string",
            "description": "Short conversational greeting + high-level "
            "topical overview (1-2 sentences).",
        },
        "highlights": {
            "type": "array",
            # Output schemas only allow minItems 0/1 and reject maxItems
            # outright — the 2-4 range is enforced by the prompt text.
            "minItems": 1,
            "items": {"type": "string"},
            "description": "Bulleted highlights, each anchored on one "
            "concrete item.",
        },
    }
    required = ["intro", "highlights"]
    if include_blurbs:
        properties["item_blurbs"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "blurb": {"type": "string"},
                },
                "required": ["item_id", "blurb"],
                "additionalProperties": False,
            },
        }
        required.append("item_blurbs")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

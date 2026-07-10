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
            "description": "The personalized opening paragraph.",
        },
    }
    required = ["intro"]
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

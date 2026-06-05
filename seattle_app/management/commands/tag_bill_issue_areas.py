"""Tag Seattle City Council bills with issue-area labels via Claude Batch.

Submits each bill's title (plus the first 2k chars of ``BillText.text`` when
available) to Claude with a constrained-vocabulary JSON schema, then writes the
returned 1-3 tags to a dedicated ``BillTags`` row — not the OCD ``Bill.subject``
field, which the scrape importer resets to ``[]`` on every re-import (#217).

The tag vocabulary is fixed in ``claude_service.BILL_TAG_VOCABULARY``; output is
enum-constrained so the model can't invent new tags. Bills without a title are
skipped (the OCD scraper occasionally emits placeholder rows).

The drain-then-submit state machine lives in ``BatchPipelineCommand``: one run
polls + persists any in-flight batch, then submits a fresh one. State is the
``BatchRun`` row, not a JSON file (issue #208). Idempotent: bills that already
have a ``BillTags`` row are excluded unless ``--force``.

Usage:
    python manage.py tag_bill_issue_areas
    python manage.py tag_bill_issue_areas --limit 5      # smoke run
    python manage.py tag_bill_issue_areas --force        # re-tag all
    python manage.py tag_bill_issue_areas --dry-run      # no API calls
    python manage.py tag_bill_issue_areas --bill "CB 121177"
"""
from __future__ import annotations

import logging
from typing import Optional

from councilmatic_core.models import Bill

from seattle_app.models import BillTags
from seattle_app.services.batch_pipeline import BatchPipelineCommand
from seattle_app.services.claude_service import (
    BILL_TAG_OUTPUT_SCHEMA,
    BILL_TAG_SYSTEM_PROMPT,
    BILL_TAG_VOCABULARY,
    _supports_adaptive_thinking,
)

logger = logging.getLogger(__name__)

# Per-request token ceiling. Tagging is a tiny structured-JSON task — the output
# is at most ~50 tokens (3 short tag strings). ``low`` effort is plenty for the
# routing decision; non-Haiku models bound thinking via ``output_config.effort``
# (Haiku doesn't accept the parameter at all).
MAX_TOKENS_PER_REQUEST = 2048
THINKING_EFFORT = "low"

# Hard cap on how much of BillText.text we feed the tagger. The bill title is
# the dominant signal; the body text is a tiebreaker for procedural bills.
# 2 kB keeps batch input cheap and uniform.
MAX_BILL_BODY_CHARS = 2_000


def _encode_custom_id(identifier: str) -> str:
    return identifier.replace(" ", "_")


def _decode_custom_id(custom_id: str) -> str:
    return custom_id.replace("_", " ")


class Command(BatchPipelineCommand):
    help = "Tag bills with issue-area labels via the Claude Batch API."

    command_key = "tag_bill_issue_areas"
    default_model_setting = "CLAUDE_BILL_TAG_MODEL"

    def add_batch_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Max number of bills to include in this batch (testing).",
        )
        parser.add_argument(
            "--bill", default=None,
            help="Single bill identifier to process (e.g. 'CB 121177').",
        )
        parser.add_argument(
            "--bills", default=None,
            help=(
                "Comma-separated bill identifiers to process. Useful for "
                "curated stress-test runs across diverse topics."
            ),
        )

    def no_targets_message(self) -> str:
        return "No bills need tagging. Done."

    # ------------------------------------------------------------------ #
    #  Target selection                                                   #
    # ------------------------------------------------------------------ #
    def get_targets(self, opts) -> list:
        bill_ids = (
            [s.strip() for s in opts["bills"].split(",") if s.strip()]
            if opts.get("bills")
            else None
        )
        return self._target_bills(
            force=opts["force"],
            limit=opts["limit"],
            bill_identifier=opts["bill"],
            bill_identifiers=bill_ids,
        )

    def _target_bills(
        self,
        *,
        force: bool,
        limit: Optional[int],
        bill_identifier: Optional[str],
        bill_identifiers: Optional[list[str]] = None,
    ) -> list:
        qs = (
            Bill.objects
            .exclude(title="")
            .select_related("extracted_text")
            .order_by("-created_at")
        )
        if bill_identifier:
            qs = qs.filter(identifier=bill_identifier)
        elif bill_identifiers:
            qs = qs.filter(identifier__in=bill_identifiers)
        elif not force:
            # Bills with no BillTags row yet. (Tags moved off OCD Bill.subject,
            # which the scrape importer resets to [] on every re-import — #217.)
            qs = qs.filter(issue_tags__isnull=True)
        if limit is not None:
            qs = qs[:limit]
        return list(qs)

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def build_requests(self, targets, model) -> list[dict]:
        requests = []
        for bill in targets:
            params = {
                "model": model,
                "max_tokens": MAX_TOKENS_PER_REQUEST,
                "system": [{
                    "type": "text",
                    "text": BILL_TAG_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": [{"role": "user", "content": self._build_input(bill)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": BILL_TAG_OUTPUT_SCHEMA,
                    },
                },
            }
            if _supports_adaptive_thinking(model):
                params["thinking"] = {"type": "adaptive"}
                params["output_config"]["effort"] = THINKING_EFFORT
            requests.append({
                "custom_id": _encode_custom_id(bill.identifier),
                "params": params,
            })
        return requests

    def describe_dry_run(self, targets, model) -> str:
        total_chars = sum(len(self._build_input(b)) for b in targets)
        return (
            f"[dry-run] Would submit {len(targets)} bill(s) with model {model}.\n"
            f"          Total input: {total_chars:,} chars "
            f"(~{total_chars // 4:,} tokens, plus cached system prompt)\n"
            f"          First 5: {[b.identifier for b in targets[:5]]}"
        )

    @staticmethod
    def _build_input(bill) -> str:
        title = (bill.title or "").strip()
        body = ""
        bt = getattr(bill, "extracted_text", None)
        if bt and bt.text:
            body = bt.text[:MAX_BILL_BODY_CHARS].strip()
        parts = [
            f"Bill: {bill.identifier}",
            f"Title: {title}",
        ]
        if body:
            parts.append("")
            parts.append("Excerpt of bill text (truncated for tagging):")
            parts.append(body)
        parts.append("")
        parts.append(
            "Return 1-3 issue-area tags from the controlled vocabulary, "
            "ordered by relevance."
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    #  Persist                                                            #
    # ------------------------------------------------------------------ #
    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        valid_tags = set(BILL_TAG_VOCABULARY)
        parsed = list(self.iter_json_results(results))
        identifiers = [_decode_custom_id(cid) for cid, _d, _m, _e in parsed]
        bills_by_id = {
            b.identifier: b
            for b in Bill.objects.filter(identifier__in=identifiers)
        }

        success = 0
        errors: list[tuple[str, str]] = []
        for cid, data, model_version, err in parsed:
            identifier = _decode_custom_id(cid)
            if err:
                errors.append((identifier, err))
                continue
            tags_raw = data.get("tags") or []
            # Schema enforces the enum but not array length (Anthropic rejects
            # minItems/maxItems on arrays), so cap and dedupe here. Order is
            # preserved (most-relevant first per prompt).
            tags: list[str] = []
            for t in tags_raw:
                if t in valid_tags and t not in tags:
                    tags.append(t)
                if len(tags) == 3:
                    break
            if not tags:
                errors.append((identifier, f"no valid tags in output: {tags_raw!r}"))
                continue
            bill = bills_by_id.get(identifier)
            if bill is None:
                errors.append((identifier, "bill not in DB"))
                continue
            BillTags.objects.update_or_create(
                bill=bill,
                defaults={
                    "tags": tags,
                    "model_version": model_version or "",
                    "tagged_batch_id": batch_id,
                },
            )
            success += 1
        return success, errors

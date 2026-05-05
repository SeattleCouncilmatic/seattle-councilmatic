"""Seed `seattle_app/data/split_decisions.json` — Haiku verdicts for
the algorithm's word-split proposals.

Workflow
========

Pure WordNinja-based splitting on SMC body text gets ~80% of merges
right but mishandles legal terminology (`thereof` → `there of`,
`grantee` → `grant ee`, `easement` → `ease ment`, ~hundreds more).
The cost-effective fix is a one-shot Haiku review of the *unique
decision space* (each `(original_token, proposed_split)` pair is
reviewed once regardless of how often it appears in the corpus),
producing a verdict file the cleanup command consults at runtime.

This command does that review:

1. **Extract phase.** Walks every `MunicipalCodeSection.full_text`,
   replays the algorithmic splitter, and accumulates a frequency-
   ordered list of unique `(original, suggested)` pairs.

2. **Review phase.** Sends batches of decisions to Haiku via the
   sync Messages API. Each response is structured JSON:
   ``{"verdict": "split"|"keep"|"fix", "split"?: "fixed split"}``.
   Saves verdicts incrementally so the command is restartable if a
   call fails mid-run.

3. **Output.** Writes `seattle_app/data/split_decisions.json`. The
   cleanup command (`clean_section_full_text`) reads this file and
   defers to its verdicts; the algorithm-only path is the fallback
   when no verdict exists for a token.

Usage
=====

::

    # Extract only — produces data/split_decisions_pending.json
    python manage.py seed_split_decisions --extract-only

    # Top-N pass (start here; covers most occurrences):
    python manage.py seed_split_decisions --limit 1000

    # Full corpus:
    python manage.py seed_split_decisions

The committed verdict file lives in source control so re-runs of
``clean_section_full_text`` are deterministic and re-parses don't
regenerate ambiguity.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from seattle_app.management.commands.clean_section_full_text import (
    _CAMEL,
    _LETTER_RUN,
    _TOKEN_MIN_LEN,
    _KEEP_MERGED,
)
from seattle_app.models import MunicipalCodeSection

import wordninja


REPO_ROOT = Path(settings.BASE_DIR)
PENDING_PATH = REPO_ROOT / "data" / "split_decisions_pending.json"
VERDICTS_PATH = REPO_ROOT / "seattle_app" / "data" / "split_decisions.json"

# Decisions per Haiku call. Balances latency (smaller = more calls)
# against output token cost (larger = bigger response). 25 is roughly
# the sweet spot — small enough to keep response JSON parseable
# without truncation risk, large enough to amortize the cached
# system prompt cost.
BATCH_SIZE = 25

SYSTEM_PROMPT = """\
You are reviewing word-split proposals from a PDF text extraction of \
the Seattle Municipal Code. The PDF parser merges adjacent words on \
tight-kerning pages (so "of the" → "ofthe", "Director of" → "Directorof"), \
and a frequency-based algorithm has proposed splits for the merged tokens.

Your job: for each proposal, decide whether the algorithm got it right.

Output JSON: a list of verdicts, one per input decision, in the same order. \
Each verdict has shape:

  {"verdict": "split"} — the proposed split is correct; apply it
  {"verdict": "keep"}  — the original token is actually a single \
English/legal word and should NOT be split (e.g. "thereof", "easement")
  {"verdict": "fix", "split": "..."} — the proposed split is wrong; \
provide the correct split

Context: this is legal/regulatory text. Many compound legal words look \
splittable to a general-English splitter but are single tokens in legal \
usage. Examples of words to KEEP MERGED:
  - thereof, thereto, therein, therefor, herein
  - grantee, designee, permittee, lessee, mortgagee, assignee
  - easement, moorage, riparian, rezone
  - Subchapter, subchapter, multifamily, nonconforming, nonresidential, centerline
  - On the other hand, "Cityof" → "City of", "Departmentof" → "Department of", \
"ofthe" → "of the" are correct splits.

When a split is wrong (e.g. "feeshall" → "fees hall"), output "fix" with the \
correct split (here: "fee shall"). Use surrounding regulatory-text context to \
disambiguate.

Output ONLY the JSON array, no prose.
"""


class Command(BaseCommand):
    help = "Generate split_decisions.json via Haiku review of algorithmic proposals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--extract-only",
            action="store_true",
            help="Only do phase 1 (extract). Writes the pending file and exits.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the top-N decisions by occurrence count. "
                 "Useful for staged rollouts (top 1000 covers ~half the occurrences).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run extract phase + report counts; no Haiku calls.",
        )

    def handle(self, *args, **options):
        # Phase 1: extract
        decisions = self._extract_decisions()
        PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        PENDING_PATH.write_text(json.dumps(decisions, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"Extracted {len(decisions)} unique split decisions "
            f"({sum(d['occurrences'] for d in decisions)} occurrences). "
            f"Wrote {PENDING_PATH}."
        ))
        if options["extract_only"] or options["dry_run"]:
            return

        # Phase 2: review
        if options["limit"]:
            decisions = decisions[: options["limit"]]
            self.stdout.write(f"Limiting to top {len(decisions)} decisions by frequency.")

        verdicts = self._load_existing_verdicts()
        unreviewed = [d for d in decisions if d["original"] not in verdicts]
        self.stdout.write(
            f"{len(verdicts)} decisions already reviewed; "
            f"{len(unreviewed)} pending."
        )
        if not unreviewed:
            self._write_verdicts(verdicts)
            return

        if not settings.ANTHROPIC_API_KEY:
            raise CommandError("ANTHROPIC_API_KEY is not configured.")
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        model = settings.CLAUDE_CODE_SECTION_MODEL  # haiku-tier model in dev

        for i in range(0, len(unreviewed), BATCH_SIZE):
            chunk = unreviewed[i : i + BATCH_SIZE]
            try:
                new_verdicts = self._call_haiku(client, model, chunk)
            except Exception as e:
                self.stderr.write(self.style.WARNING(
                    f"Chunk {i // BATCH_SIZE} failed: {e}. Saving progress and continuing."
                ))
                self._write_verdicts(verdicts)
                continue
            verdicts.update(new_verdicts)
            # Save after every chunk so a crash doesn't lose work.
            self._write_verdicts(verdicts)
            self.stdout.write(
                f"  reviewed {min(i + BATCH_SIZE, len(unreviewed))}/{len(unreviewed)}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {len(verdicts)} verdicts in {VERDICTS_PATH}."
        ))

    # ------------------------------------------------------------------ #
    #  Phase 1 — extract                                                  #
    # ------------------------------------------------------------------ #

    def _extract_decisions(self) -> list[dict]:
        counter: Counter = Counter()
        for ft in MunicipalCodeSection.objects.exclude(full_text="").values_list(
            "full_text", flat=True
        ):
            for tok_match in re.finditer(r"\S+", ft):
                tok = tok_match.group(0)
                if len(tok) < _TOKEN_MIN_LEN:
                    continue
                camel_split = _CAMEL.sub(" ", tok)
                for run_match in _LETTER_RUN.finditer(camel_split):
                    run = run_match.group(0)
                    if len(run) < _TOKEN_MIN_LEN or run.isupper():
                        continue
                    if run.lower() in _KEEP_MERGED:
                        continue
                    had_cap = run[0].isupper()
                    split = wordninja.split(run.lower())
                    if len(split) > 1 and all(len(w) > 1 for w in split):
                        if had_cap:
                            split[0] = split[0].capitalize()
                        counter[(run, " ".join(split))] += 1

        # Frequency-ordered so --limit picks the highest-leverage decisions first.
        ordered = counter.most_common()
        return [
            {"original": orig, "suggested": split, "occurrences": n}
            for (orig, split), n in ordered
        ]

    # ------------------------------------------------------------------ #
    #  Phase 2 — review                                                   #
    # ------------------------------------------------------------------ #

    def _call_haiku(
        self,
        client,
        model: str,
        chunk: list[dict],
    ) -> dict:
        """Send one chunk of decisions, parse the JSON response, return
        ``{original_token: verdict_dict}`` with the Haiku verdicts."""
        user_payload = json.dumps(
            [{"original": d["original"], "suggested": d["suggested"]} for d in chunk]
        )
        message = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(b.text for b in message.content if b.type == "text").strip()
        # Strip markdown fences if Haiku adds them despite the prompt.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        verdicts_list = json.loads(text)
        if len(verdicts_list) != len(chunk):
            raise ValueError(
                f"Expected {len(chunk)} verdicts, got {len(verdicts_list)}"
            )
        return {
            d["original"]: v
            for d, v in zip(chunk, verdicts_list)
        }

    # ------------------------------------------------------------------ #
    #  IO                                                                 #
    # ------------------------------------------------------------------ #

    def _load_existing_verdicts(self) -> dict:
        if not VERDICTS_PATH.exists():
            return {}
        return json.loads(VERDICTS_PATH.read_text())

    def _write_verdicts(self, verdicts: dict) -> None:
        VERDICTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        VERDICTS_PATH.write_text(json.dumps(verdicts, indent=2, sort_keys=True))
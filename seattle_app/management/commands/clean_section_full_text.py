"""Post-process pass over `MunicipalCodeSection.full_text` to split
words that pdfplumber merged on tight-kerning pages.

Background — issue #150
=======================

`pdfplumber.extract_words(x_tolerance=2)` doesn't bridge the kerning
gap on certain body-text pages (Title 21 utility rates, 22.805
stormwater, 6.420 boilers), so neighbors get glommed into single
tokens like `TherequirementsofthisSection`,
`rulespromulgatedbytheDirectortoreceiveflows`,
`InaccordancewithRCW35.21.560`. ~1,500 sections affected with merge
counts up to 117 per section.

The earlier attempt to fix this in the parser — bumping
`x_tolerance: 2 → 3` — caused a regression: the looser tolerance
introduced 1,353 phantom sections (8,788 vs the 7,435 baseline) and
5x the parse-validation issues. See PR #162 (closed wontfix).

This pass runs *after* a clean parse and rewrites `full_text`
in-place using a regex + WordNinja split strategy. No re-parse, no
schema change, no risk to section detection.

LLM summaries are not regenerated. We verified Sonnet handles the
merged input correctly (issue #150 spot-check on 21.49.055,
6.420.100, 22.805.070); the surviving on-page rendering issue is
visual only.

Usage
=====

::

    python manage.py clean_section_full_text             # rewrite all sections
    python manage.py clean_section_full_text --dry-run   # report deltas, don't write
    python manage.py clean_section_full_text --section-number 22.805.070  # single section

Idempotent — re-running on cleaned text does nothing because clean
text doesn't match the merge heuristic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

import wordninja

from seattle_app.models import MunicipalCodeSection


# Haiku-curated verdict file. Generated once via `seed_split_decisions`,
# committed to source control so re-runs are deterministic. Optional —
# the cleanup falls back to algorithm-only behavior if missing, which
# is how this command behaves before #150's hybrid pipeline lands.
_VERDICTS_PATH = Path(settings.BASE_DIR) / "seattle_app" / "data" / "split_decisions.json"


# Letter runs (including apostrophe). Splits within a token at any
# transition between letters and other chars (digits, punctuation),
# so 'InaccordancewithRCW35.21.560' processes 'Inaccordancewith',
# 'RCW', and the digit run separately.
_LETTER_RUN = re.compile(r"[A-Za-z']+")

# camelCase boundary — used as the cheap first-pass split for tokens
# like 'throughOrdinance' or 'TherequirementsofthisSection' (after
# the first capital).
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")

# `\S+` whitespace tokenization for the outer pass.
_WS_TOKEN = re.compile(r"\S+")

# Letter-run-level skip threshold: any letter run shorter than this
# is left alone (perf — skips wordninja calls on every short word).
# Real English words at length 5+ (`house`, `apple`, `court`) are
# protected at the *acceptance* stage instead: wordninja returns
# them as a single piece so the split is rejected. Threshold of 5
# catches common merges like `ofthe`, `Codeby`, `andthen` that
# higher thresholds miss.
_TOKEN_MIN_LEN = 5

# Domain-specific compound words WordNinja doesn't recognize and
# splits incorrectly based on raw frequency stats. SMC uses these
# as single technical terms; "storm water" would be wrong in a
# Title 22.805 stormwater-management context. Lowercase keys.
# Add to this set if a re-run surfaces another false-split term.
_KEEP_MERGED = {
    "stormwater",
    "wastewater",
    "undergrounding",
    "subbasement",
    "midblock",
    "streetscape",
}


def _load_verdicts() -> dict:
    """Read the Haiku-curated verdict file. Returns ``{}`` when the
    file doesn't exist (algorithm-only mode)."""
    if not _VERDICTS_PATH.exists():
        return {}
    try:
        return json.loads(_VERDICTS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


_VERDICTS = _load_verdicts()


def _split_letter_run(m: re.Match) -> str:
    run = m.group(0)
    if len(run) < _TOKEN_MIN_LEN or run.isupper():
        return run
    if run.lower() in _KEEP_MERGED:
        return run

    # Verdict-driven path. The Haiku-curated `split_decisions.json`
    # is the source of truth for which wordninja splits to apply.
    # Without a verdict, we DON'T apply the wordninja split — leaving
    # the merged token alone is safer than risking a bad split (e.g.
    # `thereof → there of`, `easement → ease ment`). CamelCase splits
    # in `_clean_token` are still applied either way; those are
    # reliable.
    verdict = _VERDICTS.get(run)
    if not verdict:
        return run

    kind = verdict.get("verdict")
    if kind == "keep":
        return run
    if kind == "fix" and verdict.get("split"):
        return verdict["split"]
    if kind == "split":
        # Re-run wordninja to produce the actual split string. We
        # don't store the suggestion in the verdict file because it's
        # deterministic given the original token + the algorithm.
        had_cap = run[0].isupper()
        split = wordninja.split(run.lower())
        if len(split) > 1 and all(len(w) > 1 for w in split):
            if had_cap:
                split[0] = split[0].capitalize()
            return " ".join(split)
    return run


def _clean_token(tok: str) -> str:
    if len(tok) < _TOKEN_MIN_LEN:
        return tok
    # Step 1: cheap camelCase split. Almost always correct because
    # English doesn't have legitimate aA boundaries inside words
    # (proper nouns at sentence start aside).
    tok = _CAMEL.sub(" ", tok)
    # Step 2: WordNinja each long, mixed-case letter run.
    return _LETTER_RUN.sub(_split_letter_run, tok)


def clean_text(text: str) -> str:
    """Public entry point. Whitespace-tokenize, run each token through
    the camelCase + WordNinja pipeline, rejoin with single spaces."""
    if not text:
        return text
    return _WS_TOKEN.sub(lambda m: _clean_token(m.group(0)), text)


class Command(BaseCommand):
    help = "Split merged words in MunicipalCodeSection.full_text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--section-number",
            help="Only process this one section (e.g. 22.805.070). Useful for testing.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after processing N sections (with --dry-run, useful for sampling).",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        section_number = options["section_number"]
        limit = options["limit"]

        qs = MunicipalCodeSection.objects.exclude(full_text="")
        if section_number:
            qs = qs.filter(section_number=section_number)

        total = qs.count()
        changed = 0
        char_delta = 0
        sample_changes: list[tuple[str, str, str]] = []

        for i, section in enumerate(qs.iterator()):
            if limit and i >= limit:
                break
            cleaned = clean_text(section.full_text)
            if cleaned == section.full_text:
                continue
            changed += 1
            char_delta += len(cleaned) - len(section.full_text)
            if len(sample_changes) < 5:
                # Save a small representative sample for verbose output
                sample_changes.append(
                    (section.section_number, section.full_text[:200], cleaned[:200])
                )
            if not dry:
                section.full_text = cleaned
                section.save(update_fields=["full_text"])

        # Verbose sample output
        for num, before, after in sample_changes:
            self.stdout.write(self.style.NOTICE(f"\n--- {num} ---"))
            self.stdout.write(f"before: {before!r}")
            self.stdout.write(f"after:  {after!r}")

        verb = "would change" if dry else "changed"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb} {changed} of {total} sections "
            f"(net {char_delta:+d} chars from inserted spaces)."
        ))

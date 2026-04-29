"""Generate gold-standard SMC section summaries via Opus for few-shot bootstrap.

Calls the bootstrap model (Opus by default) on a small curated set of
representative sections and writes the outputs to a timestamped JSON file
under ``data/`` for human review and curation. NOT written to the DB —
these are calibration artifacts, not production summaries. Once the
curated set is locked, the bulk Sonnet command will read the chosen
file to build its cached few-shot system prompt.

Usage:
    python manage.py bootstrap_section_summaries
    python manage.py bootstrap_section_summaries --sections 8.37.020 25.05.675
    python manage.py bootstrap_section_summaries --output-dir data/iter
"""
from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from seattle_app.models import MunicipalCodeSection
from seattle_app.services.claude_service import ClaudeService


# Curated sample picks. Each represents a distinct SMC section archetype
# the bulk Sonnet run will encounter; together they teach voice + format
# across the buckets that matter (definitions, long substantive policy,
# enforcement, permit procedural, use restrictions).
DEFAULT_SECTIONS = [
    "8.37.020",   # Definitions archetype
    "25.05.675",  # Long substantive policy (longest in corpus)
    "22.170.170", # Penalty/enforcement
    "23.76.012",  # Permit-procedural
    "23.50.012",  # LUC permitted/prohibited uses
]

# Truncated copy of the section input retained alongside each summary for
# review. Full text is recoverable from the DB by section number; this
# excerpt is what we'd want to embed in the cached few-shot prompt.
EXCERPT_CHARS = 1000


class Command(BaseCommand):
    help = (
        "Generate gold-standard section summaries via the bootstrap model "
        "(Opus by default) for few-shot calibration. Writes JSON to data/."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sections",
            nargs="+",
            default=None,
            metavar="SECTION_NUMBER",
            help=(
                "Section numbers to summarize. Defaults to the curated set "
                "of 5 archetypes."
            ),
        )
        parser.add_argument(
            "--output-dir",
            default="data",
            help="Directory to write the timestamped JSON output (default: data/).",
        )
        parser.add_argument(
            "--model",
            default=None,
            help=(
                "Override the bootstrap model. Defaults to "
                "settings.CLAUDE_BOOTSTRAP_MODEL."
            ),
        )

    def handle(self, *args, **opts):
        section_numbers = opts["sections"] or DEFAULT_SECTIONS
        output_dir = Path(opts["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        service = ClaudeService()
        model = opts["model"] or settings.CLAUDE_BOOTSTRAP_MODEL

        timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = output_dir / f"few_shot_section_summaries_{timestamp}.json"

        self.stdout.write(
            f"Bootstrapping {len(section_numbers)} section summaries via {model}"
        )
        self.stdout.write(f"Writing to {output_path}\n")

        examples: list[dict] = []
        for section_number in section_numbers:
            try:
                section = MunicipalCodeSection.objects.get(
                    section_number=section_number
                )
            except MunicipalCodeSection.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f"  ! {section_number}: not in DB, skipping"
                ))
                continue

            self.stdout.write(self.style.NOTICE(
                f"\n--- {section_number}: {section.title} "
                f"({len(section.full_text)} chars) ---"
            ))

            summary, model_version = service.summarize_code_section(
                section_number=section.section_number,
                title=section.title,
                full_text=section.full_text,
                model=model,
            )

            self.stdout.write(summary)

            examples.append({
                "section_number": section.section_number,
                "title": section.title,
                "input_chars": len(section.full_text),
                "input_excerpt": section.full_text[:EXCERPT_CHARS],
                "summary": summary,
                "summary_chars": len(summary),
                "model_version": model_version,
                "generated_at": datetime.now(dt_timezone.utc).isoformat(),
            })

            # Persist incrementally so a partial run isn't lost on later error.
            output_path.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(dt_timezone.utc).isoformat(),
                        "model": model,
                        "examples": examples,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nWrote {len(examples)} example(s) to {output_path}"
        ))

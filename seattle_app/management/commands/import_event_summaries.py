"""Import EventSummary rows from a JSON export produced on another
environment (typically dev → prod).

Lets you skip a re-run of ``summarize_events`` when the dev DB
already has the summaries you want on prod, saving the LLM cost
of regenerating them.

Matches rows by ``legistar_event_id`` (an integer from Legistar
that's deterministic across environments) rather than by OCD
``event_id`` (which is a per-environment UUID — pupa generates a
new one on first scrape in each DB, so dev and prod IDs diverge
even for the same meeting).

Skips silently when the matching Event isn't present in the local
DB — useful when the source environment scraped events the target
hasn't seen yet. Re-running is idempotent (UPSERT on ``event_id``).

Note: ``EventSummary.generated_at`` and ``created_at`` are
``auto_now`` / ``auto_now_add`` and will reflect the import time,
not the original generation time on the source environment. The
``stats_snapshot`` and ``summary_batch_id`` fields are preserved
verbatim so the LLM run is still auditable.

Companion export: there's no symmetric ``export_event_summaries``
command because the export shape is trivial — a 10-line Django
shell snippet that builds the JSON. See the commit message for
the snippet.

Usage:
    python manage.py import_event_summaries
    python manage.py import_event_summaries --input /app/data/eventsummaries-export.json
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from councilmatic_core.models import Event

from seattle_app.models import EventSummary


_DEFAULT_INPUT = "data/eventsummaries-export.json"


class Command(BaseCommand):
    help = (
        "Import EventSummary rows from a JSON export. Matches by "
        "legistar_event_id; idempotent UPSERT by event_id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default=_DEFAULT_INPUT,
            help=f"Path to the JSON export file (default: {_DEFAULT_INPUT}).",
        )

    def handle(self, *args, **opts):
        path = Path(opts["input"])
        if not path.exists():
            raise CommandError(f"Export file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        # Build a one-shot map from legistar_event_id → local
        # Event.id so the per-row lookup below is O(1).
        leg_to_event_id: dict[int, str] = {}
        for e in Event.objects.all().only("id", "extras"):
            leg_id = (e.extras or {}).get("legistar_event_id")
            if leg_id is not None:
                leg_to_event_id[int(leg_id)] = e.id

        n_ok = 0
        n_missing = 0
        for row in data:
            event_id = leg_to_event_id.get(row["legistar_event_id"])
            if not event_id:
                n_missing += 1
                continue
            EventSummary.objects.update_or_create(
                event_id=event_id,
                defaults={
                    "overview":         row["overview"],
                    "item_summaries":   row["item_summaries"],
                    "stats_snapshot":   row["stats_snapshot"],
                    "model_version":    row["model_version"],
                    "summary_batch_id": row["summary_batch_id"],
                },
            )
            n_ok += 1

        self.stdout.write(self.style.SUCCESS(
            f"Upserted: {n_ok}. Missing event in local DB: {n_missing}."
        ))

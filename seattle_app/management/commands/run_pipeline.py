"""Orchestrate one pipeline cycle as instrumented steps (issue #214).

Replaces the bash step-sequences (``update_seattle.sh`` etc.). Creates the
``PipelineRun`` at the top — so it brackets the *whole* cycle, scrape included,
not just the LLM phase — then runs each step wrapped in a ``PipelineStep``
recording status, timing, and a tail of its output. The full output is echoed to
stdout too, so it still lands in the flat cron log (joined by ``run_key``).

Batch commands are ``call_command``'d here; they attach to this run via the
``PIPELINE_RUN_KEY`` env var and, finding it pre-existing, leave the run's
lifecycle to this orchestrator (see ``get_or_create_pipeline_run``).

A failed step marks itself + the run ``failed`` and aborts the cycle (matching
the old ``set -e``); the per-item "Errors: N" that commands exit 0 on are *not*
step failures.

``--dry-run`` previews a cycle without side effects: the LLM-batch steps run with
``--dry-run`` (no API submit), and steps that don't support it (scrape / sync /
extract) are recorded ``skipped``.

Usage:
    python manage.py run_pipeline --kind full-cycle
    python manage.py run_pipeline --kind offset-drain
    python manage.py run_pipeline --kind weekly-rep
    python manage.py run_pipeline --kind offset-drain --dry-run
"""
from __future__ import annotations

import io
import os
import subprocess
from datetime import datetime, timezone as dt_timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from seattle_app.models import PipelineRun, PipelineStep
from seattle_app.services.batch_pipeline import get_or_create_pipeline_run

# Max chars of a step's output kept in PipelineStep.output (the full text is in
# the flat log, joined by run_key).
_OUTPUT_TAIL_CHARS = 4000

# Per-kind step lists. ("name", type, target, dry_ok):
#   type "pupa"  -> shell out to the pupa CLI
#   type "manage"-> run a Django management command in-process
#   dry_ok       -> in --dry-run mode this step runs with dry_run=True (the LLM
#                   batch commands); steps without it are recorded "skipped".
_STEP_LISTS = {
    PipelineRun.KIND_FULL_CYCLE: [
        ("pupa_scrape", "pupa", None, False),
        ("sync", "manage", "sync_councilmatic", False),
        ("extract_bill_text", "manage", "extract_bill_text", False),
        ("extract_transcripts", "manage", "extract_event_transcripts", False),
        ("tag_bill_issue_areas", "manage", "tag_bill_issue_areas", True),
        ("summarize_legislation", "manage", "summarize_legislation", True),
        ("summarize_events", "manage", "summarize_events", True),
    ],
    PipelineRun.KIND_OFFSET_DRAIN: [
        ("tag_bill_issue_areas", "manage", "tag_bill_issue_areas", True),
        ("summarize_legislation", "manage", "summarize_legislation", True),
        ("summarize_events", "manage", "summarize_events", True),
        ("summarize_reps", "manage", "summarize_reps", True),
    ],
    PipelineRun.KIND_WEEKLY_REP: [
        ("scrape_rep_bios", "manage", "scrape_rep_bios", False),
        ("summarize_reps", "manage", "summarize_reps", True),
    ],
}


class Command(BaseCommand):
    help = "Run one pipeline cycle (scrape → extract → LLM batches) with per-step tracking."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind", required=True, choices=list(_STEP_LISTS),
            help="Which cycle to run.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview: LLM-batch steps run --dry-run; scrape/extract steps are skipped.",
        )
        parser.add_argument(
            "--run-key", default=None,
            help="Override the generated run key (testing).",
        )

    def handle(self, *args, **opts):
        kind = opts["kind"]
        dry_run = opts["dry_run"]
        steps = _STEP_LISTS[kind]

        run_key = opts["run_key"] or f"run_{datetime.now(dt_timezone.utc):%Y%m%dT%H%M%SZ}"
        # Set the env so call_command'd batch commands attach to this run; the
        # orchestrator owns the lifecycle (they find it pre-existing).
        os.environ["PIPELINE_RUN_KEY"] = run_key
        os.environ["PIPELINE_RUN_KIND"] = kind
        run, _ = get_or_create_pipeline_run()

        n = len(steps)
        self.stdout.write(
            f"[{run_key}] pipeline start (kind={kind}, {n} steps"
            f"{', dry-run' if dry_run else ''})"
        )

        for i, (name, step_type, target, dry_ok) in enumerate(steps, start=1):
            step = PipelineStep.objects.create(
                pipeline_run=run, name=name, ordinal=i,
                status=PipelineStep.STATUS_RUNNING,
            )

            if dry_run and not dry_ok:
                step.status = PipelineStep.STATUS_SKIPPED
                step.finished_at = timezone.now()
                step.output = "(skipped — --dry-run)"
                step.save()
                self.stdout.write(f"[{run_key}] step {i}/{n}: {name} — skipped (dry-run)")
                continue

            self.stdout.write(f"[{run_key}] step {i}/{n}: {name} …")
            buf = io.StringIO()
            ok = True
            error_text = ""
            metrics: dict = {}
            try:
                if step_type == "pupa":
                    # pupa reads django.conf.settings.LOGGING and only defaults
                    # DJANGO_SETTINGS_MODULE to pupa.settings when it's unset.
                    # Under manage.py it's seattle_app.settings, which defines no
                    # LOGGING (so it's Django's default {}), and pupa then does
                    # settings.LOGGING["handlers"]… -> KeyError. Drop it so pupa
                    # uses its own settings, exactly as the bash cron call did.
                    pupa_env = os.environ.copy()
                    pupa_env.pop("DJANGO_SETTINGS_MODULE", None)
                    proc = subprocess.run(
                        ["pupa", "update", "seattle"],
                        capture_output=True, text=True, env=pupa_env,
                    )
                    buf.write((proc.stdout or "") + (proc.stderr or ""))
                    metrics["returncode"] = proc.returncode
                    ok = proc.returncode == 0
                    if not ok:
                        error_text = f"pupa exited {proc.returncode}"
                else:
                    kwargs = {"stdout": buf, "stderr": buf}
                    if dry_run:
                        kwargs["dry_run"] = True
                    call_command(target, **kwargs)
            except Exception as e:
                ok = False
                error_text = f"{type(e).__name__}: {e}"
                buf.write("\n" + error_text + "\n")

            output = buf.getvalue()
            if output:
                # Echo to the flat cron log (joined to this row by run_key).
                self.stdout.write(output, ending="")

            step.status = (
                PipelineStep.STATUS_SUCCESS if ok else PipelineStep.STATUS_FAILED
            )
            step.finished_at = timezone.now()
            step.output = output[-_OUTPUT_TAIL_CHARS:]
            step.metrics = metrics
            step.save()

            if not ok:
                run.status = PipelineRun.STATUS_FAILED
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "finished_at"])
                raise CommandError(
                    f"[{run_key}] step {i}/{n} ({name}) failed: {error_text}"
                )

        run.status = PipelineRun.STATUS_SUCCESS
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        self.stdout.write(self.style.SUCCESS(f"[{run_key}] pipeline complete ({n} steps)."))

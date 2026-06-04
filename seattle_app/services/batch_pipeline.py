"""Shared drain-then-submit state machine for the Anthropic Batch commands.

Replaces the per-command JSON state files (``data/*_state.json``) with the
DB-backed ``PipelineRun`` / ``BatchRun`` models (issue #208). Each of the four
Batch commands subclasses :class:`BatchPipelineCommand` and implements a few
hooks; the base owns the orchestration:

  * get/create the :class:`PipelineRun` for this cron cycle — ``run_key`` comes
    from the ``PIPELINE_RUN_KEY`` env var the scheduler exports, so every
    command in a cycle attaches to one run; a bare ``manage.py`` call with no
    env var mints its own ``kind="manual"`` run so ad-hoc work is still tracked,
  * drain any in-flight ``BatchRun`` for this command (poll Anthropic, persist
    results via the subclass, mark the ``BatchRun`` processed),
  * then submit a fresh batch for newly-unprocessed rows, recording a new
    ``BatchRun``.

So one invocation both drains the prior batch and submits new work — the
behaviour the 6h scheduler relies on (issues #204, #206, #207). "Is there an
in-flight batch for this command?" — asked every run — is a DB query here, so
state survives container recreates / deploys (unlike the old JSON files).
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import datetime, timezone as dt_timezone

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from seattle_app.models import BatchRun, PipelineRun
from seattle_app.services.claude_service import format_batch_error

logger = logging.getLogger(__name__)

# Correlation id for the current pipeline run. Stamped onto every flat-log line
# by the logging filter below once it's wired into LOGGING (#205); also inlined
# into the operator-facing stdout lines here so a row in the DB always joins to
# the deep-debug log by run_key / batch_id.
run_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pipeline_run_key", default="-"
)


class PipelineRunKeyFilter(logging.Filter):
    """Injects the current ``run_key`` into every log record so a formatter can
    prefix ``[%(run_key)s]``. Wired into ``LOGGING`` in #205."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_key = run_key_var.get()
        return True


def get_or_create_pipeline_run() -> PipelineRun:
    """Return the :class:`PipelineRun` for this invocation. All commands in one
    cron cycle share a run via the ``PIPELINE_RUN_KEY`` env var the scheduler
    sets; a bare ``manage.py`` call (no env var) mints its own manual run."""
    run_key = os.environ.get("PIPELINE_RUN_KEY", "").strip()
    kind = os.environ.get("PIPELINE_RUN_KIND", "").strip()
    if run_key:
        run, _ = PipelineRun.objects.get_or_create(
            run_key=run_key,
            defaults={"kind": kind or PipelineRun.KIND_FULL_CYCLE},
        )
    else:
        stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run = PipelineRun.objects.create(
            run_key=f"run_{stamp}_manual",
            kind=PipelineRun.KIND_MANUAL,
        )
    run_key_var.set(run.run_key)
    return run


class BatchPipelineCommand(BaseCommand):
    """Base for the four Anthropic Batch management commands.

    Subclasses set :attr:`command_key` + :attr:`default_model_setting` and
    implement :meth:`get_targets`, :meth:`build_requests`,
    :meth:`persist_results`, :meth:`describe_dry_run`, and
    :meth:`no_targets_message`. The base owns the drain-then-submit state
    machine and the ``PipelineRun`` / ``BatchRun`` bookkeeping.
    """

    #: Must match a ``BatchRun.command`` choice, e.g. ``"summarize_events"``.
    command_key: str = ""
    #: ``settings`` attribute holding the default model, e.g.
    #: ``"CLAUDE_EVENT_SUMMARY_MODEL"``.
    default_model_setting: str = ""

    # ------------------------------------------------------------------ #
    #  Hooks subclasses implement                                         #
    # ------------------------------------------------------------------ #
    def add_batch_arguments(self, parser) -> None:
        """Add command-specific CLI args (e.g. ``--event-id``). Optional."""

    def get_targets(self, opts) -> list:
        """Return the list of rows needing a batch (honouring ``--force`` and
        any command-specific selectors). Empty list ⇒ nothing to submit."""
        raise NotImplementedError

    def build_requests(self, targets, model) -> list[dict]:
        """Build the Anthropic Batch ``requests`` list for ``targets``."""
        raise NotImplementedError

    def persist_results(self, results, batch_id: str) -> tuple[int, list]:
        """Persist a finished batch's results to the DB. Return
        ``(success_count, errors)`` where ``errors`` is a list of
        ``(item_id, message)`` pairs. Use :meth:`iter_json_results` to share
        the result-parsing scaffolding."""
        raise NotImplementedError

    def describe_dry_run(self, targets, model) -> str:
        return f"[dry-run] Would submit {len(targets)} item(s) with model {model}."

    def no_targets_message(self) -> str:
        return "Nothing to do. Done."

    # ------------------------------------------------------------------ #
    #  Argument wiring                                                    #
    # ------------------------------------------------------------------ #
    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be submitted without calling the API.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Re-process rows that already have output.",
        )
        parser.add_argument(
            "--model", default=None,
            help=f"Override settings.{self.default_model_setting} for this run.",
        )
        self.add_batch_arguments(parser)

    # ------------------------------------------------------------------ #
    #  Orchestration — drain then submit                                  #
    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        if not getattr(settings, "ANTHROPIC_API_KEY", ""):
            raise CommandError("ANTHROPIC_API_KEY not configured.")
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        run = get_or_create_pipeline_run()
        try:
            inflight = (
                BatchRun.objects.filter(
                    command=self.command_key,
                    status__in=[BatchRun.STATUS_SUBMITTED, BatchRun.STATUS_IN_PROGRESS],
                )
                .order_by("submitted_at")
                .first()
            )
            if inflight is not None:
                ended = self._drain(client, inflight, run)
                if not ended:
                    return  # batch still in flight; drained on the next run
                # ended + persisted → fall through and submit fresh work
            self._submit(client, opts, run)
        except Exception:
            self._finish_run(run, PipelineRun.STATUS_FAILED)
            raise
        else:
            self._finish_run(run, PipelineRun.STATUS_SUCCESS)

    # ------------------------------------------------------------------ #
    #  Drain                                                              #
    # ------------------------------------------------------------------ #
    def _drain(self, client, batchrun: BatchRun, run: PipelineRun) -> bool:
        rk = run.run_key
        self.stdout.write(
            f"[{rk}] {self.command_key}: polling batch {batchrun.batch_id}…"
        )
        batch = client.messages.batches.retrieve(batchrun.batch_id)
        status = getattr(batch, "processing_status", None)
        counts = getattr(batch, "request_counts", None)
        if counts is not None:
            self.stdout.write(
                f"  counts: processing={getattr(counts, 'processing', '?')} "
                f"succeeded={getattr(counts, 'succeeded', '?')} "
                f"errored={getattr(counts, 'errored', '?')} "
                f"canceled={getattr(counts, 'canceled', '?')} "
                f"expired={getattr(counts, 'expired', '?')}"
            )

        if status != "ended":
            if batchrun.status != BatchRun.STATUS_IN_PROGRESS:
                batchrun.status = BatchRun.STATUS_IN_PROGRESS
                batchrun.save(update_fields=["status", "updated_at"])
            self.stdout.write(self.style.NOTICE(
                "  batch not yet ended; will drain on the next run."
            ))
            return False

        results = list(client.messages.batches.results(batchrun.batch_id))
        success, errors = self.persist_results(results, batchrun.batch_id)
        batchrun.status = BatchRun.STATUS_PROCESSED
        batchrun.success_count = success
        batchrun.error_count = len(errors)
        batchrun.errors = [list(e) for e in errors[:50]]
        batchrun.processed_at = timezone.now()
        batchrun.processed_in_run = run
        batchrun.save()
        self.stdout.write(self.style.SUCCESS(
            f"[{rk}] {self.command_key}: drained {batchrun.batch_id} — "
            f"{success} ok, {len(errors)} errored."
        ))
        if errors:
            self.stdout.write(self.style.WARNING(f"  first errors: {errors[:5]}"))
        return True

    # ------------------------------------------------------------------ #
    #  Submit                                                             #
    # ------------------------------------------------------------------ #
    def _submit(self, client, opts, run: PipelineRun):
        targets = self.get_targets(opts)
        if not targets:
            self.stdout.write(self.style.SUCCESS(self.no_targets_message()))
            return
        model = opts.get("model") or getattr(settings, self.default_model_setting)
        if opts.get("dry_run"):
            self.stdout.write(self.describe_dry_run(targets, model))
            return
        requests = self.build_requests(targets, model)
        batch = client.messages.batches.create(requests=requests)
        BatchRun.objects.create(
            command=self.command_key,
            batch_id=batch.id,
            model=model,
            item_count=len(targets),
            status=BatchRun.STATUS_SUBMITTED,
            submitted_in_run=run,
        )
        self.stdout.write(self.style.SUCCESS(
            f"[{run.run_key}] {self.command_key}: submitted batch {batch.id} "
            f"with {len(targets)} item(s), model {model}."
        ))

    # ------------------------------------------------------------------ #
    #  Run lifecycle                                                      #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _finish_run(run: PipelineRun, status: str) -> None:
        # Commands in a cycle run sequentially (the scheduler serialises them
        # under one flock), so the last one to finish stamps the run. A failure
        # aborts the script (set -e) before later commands run, so a 'failed'
        # status is never masked by a later success.
        run.status = status
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])

    # ------------------------------------------------------------------ #
    #  Shared result helpers                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_text(message) -> str:
        for block in message.content:
            if block.type == "text":
                return block.text
        return ""

    def iter_json_results(self, results):
        """Yield ``(custom_id, data, model_version, error)`` per batch result.

        On success ``data`` is the parsed JSON dict and ``model_version`` is the
        model the API echoed; on failure both are ``None`` and ``error`` is a
        diagnostic string. Centralises the succeeded/empty/non-JSON checks the
        four commands used to each copy."""
        for result in results:
            cid = result.custom_id
            if result.result.type != "succeeded":
                yield cid, None, None, format_batch_error(result.result)
                continue
            message = result.result.message
            text = self.extract_text(message)
            if not text:
                blocks = sorted({getattr(b, "type", "?") for b in message.content})
                stop = getattr(message, "stop_reason", "?")
                yield cid, None, None, f"empty text (stop={stop} blocks={blocks})"
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                yield cid, None, None, f"non-JSON output: {e}"
                continue
            yield cid, data, message.model, None

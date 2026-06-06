"""Email an alert when the LLM pipeline looks unhealthy (issue #210).

Health = a successful **full-cycle** ``PipelineRun`` finished within
``PIPELINE_HEARTBEAT_HOURS``. The heartbeat keys on full-cycle success
specifically: offset-drain runs succeed even when the scrape is wedged, so a
broken scrape (every full-cycle failing) still trips the alert.

Runs on its own cron tick, independent of ``run_pipeline`` and NOT under the
pipeline flock, so it still fires if a run is wedged holding the lock. Emails on
the healthy→unhealthy transition, re-nags at most every
``PIPELINE_ALERT_RENOTIFY_HOURS`` while unhealthy, and sends one note on
recovery. State lives in ``PipelineAlertState`` so it doesn't email every tick.

Recipients come from ``settings.PIPELINE_ALERT_EMAILS``; without SMTP configured
(``EMAIL_HOST``) the console backend logs the message to the cron log instead.

Usage:
    python manage.py check_pipeline_health
    python manage.py check_pipeline_health --dry-run   # assess only; no email/save
    python manage.py check_pipeline_health --test      # send a sample email now
"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from seattle_app.models import PipelineAlertState, PipelineRun, PipelineStep


class Command(BaseCommand):
    help = "Email an alert when the pipeline has no recent successful full-cycle."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print the assessment; don't email or update state.",
        )
        parser.add_argument(
            "--test", action="store_true",
            help="Send a sample alert email now to verify SMTP + recipients; "
                 "ignores health and doesn't touch state.",
        )

    def handle(self, *args, **opts):
        if opts["test"]:
            self._send(
                "🧪 Councilmatic pipeline: test alert",
                "Test of the pipeline health alert email. If you received this, "
                "SMTP and PIPELINE_ALERT_EMAILS are configured correctly.",
                opts["dry_run"],
            )
            return

        now = timezone.now()
        heartbeat = timedelta(hours=settings.PIPELINE_HEARTBEAT_HOURS)
        renotify = timedelta(hours=settings.PIPELINE_ALERT_RENOTIFY_HOURS)

        latest_success = (
            PipelineRun.objects
            .filter(
                kind=PipelineRun.KIND_FULL_CYCLE,
                status=PipelineRun.STATUS_SUCCESS,
                finished_at__isnull=False,
            )
            .order_by("-finished_at")
            .first()
        )
        runs_exist = PipelineRun.objects.filter(kind=PipelineRun.KIND_FULL_CYCLE).exists()
        if not runs_exist:
            healthy = True  # fresh env — no full-cycles yet, nothing to judge
        elif latest_success is None:
            healthy = False  # full-cycles have run but none succeeded
        else:
            healthy = (now - latest_success.finished_at) <= heartbeat

        # Recent failed runs for the digest (within the heartbeat window).
        failed_runs = list(
            PipelineRun.objects
            .filter(status=PipelineRun.STATUS_FAILED, finished_at__gte=now - heartbeat)
            .order_by("-finished_at")[:10]
        )

        last_success_str = (
            latest_success.finished_at.isoformat() if latest_success else "never"
        )
        self.stdout.write(
            f"health={'OK' if healthy else 'UNHEALTHY'} "
            f"last_full_cycle_success={last_success_str} "
            f"failed_runs_{settings.PIPELINE_HEARTBEAT_HOURS}h={len(failed_runs)}"
        )

        state, _ = PipelineAlertState.objects.get_or_create(pk=1)

        subject = body = None
        if not healthy:
            due = (
                state.healthy  # just transitioned unhealthy
                or state.last_alerted_at is None
                or (now - state.last_alerted_at) > renotify
            )
            if due:
                subject, body = self._unhealthy_message(latest_success, failed_runs)
        elif not state.healthy:
            subject, body = self._recovered_message(latest_success)

        if subject:
            sent = self._send(subject, body, opts["dry_run"])
            if sent and not opts["dry_run"]:
                state.last_alerted_at = now

        if not opts["dry_run"]:
            state.healthy = healthy
            state.last_checked_at = now
            state.detail = (subject or ("healthy" if healthy else "unhealthy (throttled)"))[:255]
            state.save()

    # ------------------------------------------------------------------ #
    def _unhealthy_message(self, latest_success, failed_runs):
        hrs = settings.PIPELINE_HEARTBEAT_HOURS
        last = latest_success.finished_at.isoformat() if latest_success else "never"
        lines = [
            "Seattle Councilmatic — pipeline health alert.",
            "",
            f"No successful full-cycle has completed in the last {hrs}h.",
            f"Last successful full-cycle: {last}",
            "",
        ]
        if failed_runs:
            lines.append(f"Failed runs in the last {hrs}h:")
            for r in failed_runs:
                failed_step = r.steps.filter(status=PipelineStep.STATUS_FAILED).first()
                step_note = f" — failed at step '{failed_step.name}'" if failed_step else ""
                lines.append(f"  - {r.run_key} ({r.kind}){step_note}; finished {r.finished_at}")
        else:
            lines.append(
                "No failed runs recorded either — the scheduler may be down entirely."
            )
        lines += ["", "Dashboard: /admin/seattle_app/pipelinerun/"]
        return "🔴 Councilmatic pipeline: no recent successful run", "\n".join(lines)

    def _recovered_message(self, latest_success):
        last = latest_success.finished_at.isoformat() if latest_success else "?"
        return (
            "🟢 Councilmatic pipeline: recovered",
            f"A full-cycle completed successfully at {last}. Pipeline is healthy again.",
        )

    def _send(self, subject, body, dry_run) -> bool:
        if dry_run:
            self.stdout.write(self.style.WARNING(f"[dry-run] would send:\n{subject}\n\n{body}"))
            return False
        recipients = settings.PIPELINE_ALERT_EMAILS
        if not recipients:
            self.stderr.write(self.style.WARNING(
                "PIPELINE_ALERT_EMAILS not set — assessment only, no email sent."
            ))
            return False
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients,
                      fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"Alert emailed to {recipients}."))
            return True
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send alert email: {e}"))
            return False

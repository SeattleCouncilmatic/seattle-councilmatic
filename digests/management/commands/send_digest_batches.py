"""Render and deliver pending digests, polling the intro batch first
(Phases 2-3, #235/#238).

Picks up ``DigestSend(status=pending)`` rows written by ``compose_digests``.
Rows with a ``compose_batch_id`` wait for their Anthropic Batch: once it
ends, each subscriber's ``{intro}`` is persisted to ``llm_payload`` (the
template's intro slot reads from there) and the digest renders + sends.
Rows without a batch id — quiet weeks, LLM off, submit failures — send
templated-only immediately.

The intro can delay a digest but never block it: rows still awaiting a
batch after ``LLM_MAX_DELAY`` send without the intro, and a batch that
ends in a terminal non-success state degrades the same way. ``--wait N``
keeps polling for up to N minutes (the cron wrapper uses this); the
default is a single pass.

SMTP safety: the SMTP transport is TEST-TO-SELF ONLY, never real
subscribers (no bounce handling, relay volume caps). Outside DEBUG the
command refuses to deliver over SMTP unless ``--allow-smtp`` is passed —
so the prod cron entry stays inert until Phase 4 flips
``DIGEST_EMAIL_BACKEND=postmark``.

PII discipline: log/store ``subscriber.id`` only. Exception text is
email-redacted before it's persisted to ``DigestSend.error`` (SMTP
exceptions embed the recipient address, and the field renders in the
admin); the logging path is already covered by ``EmailRedactionFilter``.

Usage:
    python manage.py send_digest_batches
    python manage.py send_digest_batches --wait 45
    python manage.py send_digest_batches --limit 5 --allow-smtp
"""
import logging
import smtplib
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.utils import timezone

from digests.models import DigestSend, Subscriber
from digests.services import personalization
from digests.services.email_client import get_email_client
from digests.services.llm_client import IN_FLIGHT_STATUSES, get_llm_client
from digests.services.tokens import PURPOSE_MANAGE, PURPOSE_UNSUBSCRIBE, make_token
from seattle_app.logging_filters import redact_emails

logger = logging.getLogger(__name__)

# A digest still waiting on its intro batch past this age sends without the
# intro. Keeps a wedged/expired batch from silently blocking the cadence
# (pending rows also block re-compose, so a stuck batch would otherwise
# swallow a whole week).
LLM_MAX_DELAY = timedelta(hours=6)

# Seconds between polls under --wait.
POLL_INTERVAL_SECONDS = 30


class Command(BaseCommand):
    help = "Render pending DigestSend rows (waiting on their intro batch when one exists) and deliver them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max pending sends to deliver this run (testing).",
        )
        parser.add_argument(
            "--wait",
            type=int,
            default=0,
            help="Keep polling the intro batch for up to N minutes instead "
            "of a single pass. The weekly cron wrapper passes this.",
        )
        parser.add_argument(
            "--allow-smtp",
            action="store_true",
            help="Deliver over the SMTP transport outside DEBUG. SMTP is "
            "test-to-self only — never point it at real subscribers.",
        )

    def handle(self, *args, **opts):
        deadline = time.monotonic() + opts["wait"] * 60
        while True:
            awaiting = self._pass(opts)
            if not awaiting:
                return
            if time.monotonic() >= deadline:
                self.stdout.write(self.style.NOTICE(
                    f"{awaiting} digest(s) still awaiting their intro batch; "
                    "re-run to poll again (they send without the intro after "
                    f"{int(LLM_MAX_DELAY.total_seconds() // 3600)}h)."
                ))
                return
            time.sleep(POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------ #

    def _pass(self, opts) -> int:
        """One poll-and-send pass. Returns how many pending rows are still
        waiting on an in-flight intro batch (0 ⇒ nothing left to wait for)."""
        pending = list(
            DigestSend.objects.filter(status=DigestSend.STATUS_PENDING)
            .select_related("subscriber")
            .order_by("created_at")[: opts["limit"]]
        )
        if not pending:
            self.stdout.write("No pending digests. Done.")
            return 0

        # Checked only when there IS something to send, so the pre-Phase-4
        # prod cron (signups closed, zero subscribers) exits quietly above
        # instead of erroring every Sunday.
        if (
            settings.DIGEST_EMAIL_BACKEND == "smtp"
            and not settings.DEBUG
            and not opts["allow_smtp"]
        ):
            raise CommandError(
                "Refusing to deliver digests over SMTP outside DEBUG: the "
                "SMTP transport is test-to-self only. Pass --allow-smtp for "
                "a deliberate test send, or configure the Postmark transport "
                "(Phase 4) for real subscribers."
            )

        ready, awaiting = self._resolve_intros(pending)

        client = get_email_client()
        sent = failed = 0
        for send in ready:
            subscriber = send.subscriber
            if subscriber.status != Subscriber.STATUS_ACTIVE:
                # Unsubscribed/bounced between compose and send. Not an
                # error worth alerting on, but the row shouldn't stay
                # pending (it would block tomorrow's dedup forever).
                send.status = DigestSend.STATUS_FAILED
                send.error = f"subscriber no longer active ({subscriber.status})"
                send.save(update_fields=["status", "error"])
                failed += 1
                continue
            try:
                self._deliver(client, send)
                sent += 1
            except smtplib.SMTPRecipientsRefused as exc:
                # Hard bounce: the relay rejected this recipient. Stop
                # sending to them (plan: failures flip status to bounced).
                subscriber.status = Subscriber.STATUS_BOUNCED
                subscriber.last_bounce_at = timezone.now()
                subscriber.save(update_fields=["status", "last_bounce_at"])
                self._mark_failed(send, exc)
                failed += 1
            except Exception as exc:  # noqa: BLE001 — one bad send must not stop the batch
                self._mark_failed(send, exc)
                failed += 1

        style = self.style.SUCCESS if not failed else self.style.WARNING
        self.stdout.write(style(
            f"Delivered {sent} digest(s); {failed} failed; "
            f"{len(awaiting)} awaiting their intro batch."
        ))
        return len(awaiting)

    def _resolve_intros(self, pending):
        """Split pending rows into (ready-to-send, still-awaiting-batch),
        persisting fetched intros onto ``llm_payload``. Degradation rules:
        no batch id → ready without intro; batch ended → ready (with intro
        when this subscriber's request succeeded); batch in a terminal
        non-success state or unpollable-because-LLM-off → ready without
        intro; in flight or transient poll error → awaiting, but never past
        LLM_MAX_DELAY."""
        batch_ids = sorted({s.compose_batch_id for s in pending if s.compose_batch_id})
        llm = get_llm_client() if batch_ids else None

        ready, awaiting = [], []
        results_by_batch: dict[str, dict | None] = {}
        for batch_id in batch_ids:
            if llm is None:
                # Composed with a batch but the backend is now off — can't
                # poll, don't wait forever.
                logger.warning(
                    "batch %s unpollable (LLM backend off); sending without intros",
                    batch_id,
                )
                results_by_batch[batch_id] = {}
                continue
            try:
                status = llm.batch_status(batch_id)
                if status == "ended":
                    results_by_batch[batch_id] = llm.batch_results(batch_id)
                elif status in IN_FLIGHT_STATUSES:
                    results_by_batch[batch_id] = None  # keep waiting
                else:
                    logger.warning(
                        "batch %s in terminal state %r; sending without intros",
                        batch_id, status,
                    )
                    results_by_batch[batch_id] = {}
            except Exception:
                # Transient API trouble: wait (the age cap below bounds it)
                # rather than strip intros from the whole cohort over a blip.
                logger.exception("polling batch %s failed", batch_id)
                results_by_batch[batch_id] = None

        now = timezone.now()
        for send in pending:
            if not send.compose_batch_id:
                ready.append(send)
                continue
            results = results_by_batch[send.compose_batch_id]
            if results is None:
                if now - send.created_at > LLM_MAX_DELAY:
                    logger.warning(
                        "digest %s exceeded LLM_MAX_DELAY; sending without intro",
                        send.id,
                    )
                    ready.append(send)
                else:
                    awaiting.append(send)
                continue
            data = results.get(f"sub-{send.subscriber_id}")
            if data:
                send.llm_payload = data
                # Persisted before delivery so a send crash can't lose the
                # fetched intro (and the future feed page can re-render it).
                send.save(update_fields=["llm_payload"])
            ready.append(send)
        return ready, awaiting

    # ------------------------------------------------------------------ #

    def _deliver(self, client, send):
        subscriber = send.subscriber
        items = personalization.items_from_snapshot(send.matched_item_ids)
        base = settings.DIGEST_SITE_BASE_URL.rstrip("/")
        unsubscribe_url = (
            f"{base}/digests/unsubscribe?token="
            f"{make_token(subscriber, PURPOSE_UNSUBSCRIBE)}"
        )
        context = {
            "cadence": send.cadence,
            "intro": (send.llm_payload or {}).get("intro"),
            "quiet": not items,
            "window_label": timezone.localdate().strftime("%B %d, %Y"),
            "bill_items": [i for i in items if i["type"] == "bill"],
            "meeting_items": [i for i in items if i["type"] == "meeting"],
            "site_base": base,
            "manage_url": (
                f"{base}/digests/manage?token="
                f"{make_token(subscriber, PURPOSE_MANAGE)}"
            ),
            "unsubscribe_url": unsubscribe_url,
            "postal_address": settings.DIGEST_POSTAL_ADDRESS,
        }
        result = client.send(
            to=subscriber.email,
            subject=self._subject(send.cadence, len(items)),
            text_body=render_to_string("email/digest.txt", context),
            html_body=render_to_string("email/digest.html", context),
            headers={
                # RFC 8058 one-click — the unsubscribe view already accepts
                # the List-Unsubscribe=One-Click POST. Included from day one
                # so the header path is exercised long before Postmark.
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
        now = timezone.now()
        send.status = DigestSend.STATUS_SENT
        send.sent_at = now
        send.postmark_message_id = result.provider_message_id
        # Snapshot items can vanish between compose and send (a re-scrape
        # dropped a bill); record what was actually rendered.
        send.item_count = len(items)
        send.error = ""
        send.save(
            update_fields=[
                "status", "sent_at", "postmark_message_id", "item_count", "error",
            ]
        )
        subscriber.last_sent_at = now
        subscriber.save(update_fields=["last_sent_at"])
        logger.info(
            "digest sent: subscriber %s, %s, %d item(s)%s",
            subscriber.id, send.cadence, len(items),
            ", with intro" if (send.llm_payload or {}).get("intro") else "",
        )

    @staticmethod
    def _subject(cadence, item_count):
        if not item_count:
            return "Seattle City Council: a quiet week"
        window = "this week" if cadence == DigestSend.CADENCE_WEEKLY else "today"
        plural = "s" if item_count != 1 else ""
        return f"Your Seattle Council digest: {item_count} update{plural} {window}"

    @staticmethod
    def _mark_failed(send, exc):
        send.status = DigestSend.STATUS_FAILED
        send.error = redact_emails(f"{exc.__class__.__name__}: {exc}")[:255]
        send.save(update_fields=["status", "error"])
        logger.exception("digest send failed: subscriber %s", send.subscriber_id)

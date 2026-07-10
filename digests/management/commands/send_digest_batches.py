"""Render and deliver pending digests (Phase 2, #235).

Picks up ``DigestSend(status=pending)`` rows written by ``compose_digests``,
re-fetches item content from the ``matched_item_ids`` snapshot, renders the
HTML + plaintext pair, and hands the message to the configured
``DigestEmailClient``. In Phase 3 this command also polls the Anthropic
Batch and merges the intro into ``llm_payload`` before rendering — the
``intro`` template slot already reads from there.

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
    python manage.py send_digest_batches --limit 5 --allow-smtp
"""
import logging
import smtplib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.utils import timezone

from digests.models import DigestSend, Subscriber
from digests.services import personalization
from digests.services.email_client import get_email_client
from digests.services.tokens import PURPOSE_MANAGE, PURPOSE_UNSUBSCRIBE, make_token
from seattle_app.logging_filters import redact_emails

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Render pending DigestSend rows and deliver them through the digest email transport."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max pending sends to deliver this run (testing).",
        )
        parser.add_argument(
            "--allow-smtp",
            action="store_true",
            help="Deliver over the SMTP transport outside DEBUG. SMTP is "
            "test-to-self only — never point it at real subscribers.",
        )

    def handle(self, *args, **opts):
        pending = list(
            DigestSend.objects.filter(status=DigestSend.STATUS_PENDING)
            .select_related("subscriber")
            .order_by("created_at")[: opts["limit"]]
        )
        if not pending:
            self.stdout.write("No pending digests. Done.")
            return

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

        client = get_email_client()
        sent = failed = 0
        for send in pending:
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
        self.stdout.write(style(f"Delivered {sent} digest(s); {failed} failed."))

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
            # Phase 3 writes {"intro": ...} to llm_payload; renders as soon
            # as it does.
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
            "digest sent: subscriber %s, %s, %d item(s)",
            subscriber.id, send.cadence, len(items),
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

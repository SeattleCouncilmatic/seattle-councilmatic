"""compose_digests / send_digest_batches pipeline tests (#235).

The Django test runner swaps in the locmem mail backend, so the SMTP
client "delivers" to ``django.core.mail.outbox``. The runner also forces
``DEBUG=False``, which is exactly what the SMTP safety guard keys on —
sends here pass ``allow_smtp=True`` except the guard test itself.
"""
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from digests.models import DigestSend, Subscriber
from digests.tests import fixtures

RECENT = (date.today() - timedelta(days=2)).isoformat()


def _compose(**kwargs):
    out = StringIO()
    call_command("compose_digests", stdout=out, **kwargs)
    return out.getvalue()


def _send(**kwargs):
    out = StringIO()
    kwargs.setdefault("allow_smtp", True)
    call_command("send_digest_batches", stdout=out, **kwargs)
    return out.getvalue()


def _tagged_bill_and_subscriber(email="compose@example.org"):
    bill = fixtures.bill(
        "CB 200001", action_date=RECENT, tags=["Housing"], summary="What it does."
    )
    sub = fixtures.subscriber(email, issue_areas=["Housing"])
    return bill, sub


class ComposeTests(TestCase):
    def test_creates_pending_row_with_snapshot(self):
        bill, sub = _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        send = DigestSend.objects.get(subscriber=sub)
        self.assertEqual(send.status, DigestSend.STATUS_PENDING)
        self.assertIsNone(send.sent_at)
        self.assertEqual(send.item_count, 1)
        self.assertEqual(
            send.matched_item_ids,
            [{"type": "bill", "id": bill.id, "reasons": ["Tagged Housing"]}],
        )

    def test_dedup_one_per_cadence_per_day(self):
        _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.count(), 1)

    def test_stale_pending_row_blocks_recompose(self):
        _, sub = _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        # Backdate: composed days ago but never sent — composing again on
        # top of it would double-send once the send command catches up.
        DigestSend.objects.update(created_at=timezone.now() - timedelta(days=3))
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.count(), 1)

    def test_sent_today_blocks_but_failed_does_not(self):
        _, sub = _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        DigestSend.objects.update(status=DigestSend.STATUS_FAILED)
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.count(), 2)

    def test_weekly_quiet_week_still_composes(self):
        sub = fixtures.subscriber("quiet@example.org", issue_areas=["Housing"])
        _compose(cadence="weekly")
        send = DigestSend.objects.get(subscriber=sub)
        self.assertEqual(send.item_count, 0)
        self.assertEqual(send.matched_item_ids, [])

    def test_daily_zero_match_skipped(self):
        fixtures.subscriber(
            "daily@example.org", issue_areas=["Housing"], daily=True
        )
        _compose(cadence="daily")
        self.assertEqual(DigestSend.objects.count(), 0)

    def test_cadence_flag_respected(self):
        # Action dated today: the daily window (last day) must catch it.
        fixtures.bill(
            "CB 200002", action_date=date.today().isoformat(), tags=["Housing"]
        )
        fixtures.subscriber(
            "weeklyoff@example.org", issue_areas=["Housing"], weekly=False, daily=True
        )
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.count(), 0)
        _compose(cadence="daily")
        self.assertEqual(DigestSend.objects.count(), 1)

    def test_only_active_subscribers(self):
        fixtures.bill("CB 200003", action_date=RECENT, tags=["Housing"])
        fixtures.subscriber(
            "pending@example.org",
            status=Subscriber.STATUS_PENDING,
            issue_areas=["Housing"],
        )
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.count(), 0)

    def test_since_override_widens_window(self):
        stale = (date.today() - timedelta(days=40)).isoformat()
        fixtures.bill("CB 200006", action_date=stale, tags=["Housing"])
        _, sub = fixtures.bill, fixtures.subscriber(
            "since@example.org", issue_areas=["Housing"]
        )
        _compose(cadence="weekly")
        self.assertEqual(DigestSend.objects.get().item_count, 0)
        DigestSend.objects.all().delete()
        _compose(
            cadence="weekly",
            since=(date.today() - timedelta(days=60)).isoformat(),
        )
        self.assertEqual(DigestSend.objects.get().item_count, 1)

    def test_dry_run_writes_nothing(self):
        _tagged_bill_and_subscriber()
        out = _compose(cadence="weekly", dry_run=True)
        self.assertEqual(DigestSend.objects.count(), 0)
        self.assertIn("1 item(s)", out)


class SendTests(TestCase):
    def test_delivers_and_marks_sent(self):
        bill, sub = _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        _send()

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [sub.email])
        self.assertIn("1 update this week", message.subject)
        text = message.body
        html = message.alternatives[0][0]
        for body in (text, html):
            self.assertIn("CB 200001", body)
            self.assertIn("Tagged Housing", body)
            self.assertIn("What it does.", body)
            self.assertIn("/legislation/cb-200001", body)
            self.assertIn("/digests/unsubscribe?token=", body)
            self.assertIn("/digests/manage?token=", body)
        self.assertIn("List-Unsubscribe", message.extra_headers)
        self.assertEqual(
            message.extra_headers["List-Unsubscribe-Post"],
            "List-Unsubscribe=One-Click",
        )

        send = DigestSend.objects.get()
        self.assertEqual(send.status, DigestSend.STATUS_SENT)
        self.assertIsNotNone(send.sent_at)
        sub.refresh_from_db()
        self.assertIsNotNone(sub.last_sent_at)

    def test_quiet_week_email(self):
        fixtures.subscriber("quietsend@example.org", issue_areas=["Housing"])
        _compose(cadence="weekly")
        _send()
        message = mail.outbox[0]
        self.assertIn("quiet week", message.subject)
        self.assertIn("quiet week", message.body)

    def test_smtp_guard_refuses_outside_debug(self):
        # Test runner forces DEBUG=False, which is the guard's real prod
        # condition — no override_settings needed.
        _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        with self.assertRaises(CommandError):
            call_command("send_digest_batches", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            DigestSend.objects.get().status, DigestSend.STATUS_PENDING
        )

    def test_no_pending_exits_before_guard(self):
        # The prod cron path: nothing to send → quiet exit, not CommandError.
        out = StringIO()
        call_command("send_digest_batches", stdout=out)
        self.assertIn("No pending digests", out.getvalue())

    def test_unsubscribed_between_compose_and_send(self):
        _, sub = _tagged_bill_and_subscriber()
        _compose(cadence="weekly")
        sub.mark_unsubscribed()
        _send()
        self.assertEqual(len(mail.outbox), 0)
        send = DigestSend.objects.get()
        self.assertEqual(send.status, DigestSend.STATUS_FAILED)
        self.assertIn("no longer active", send.error)

    def test_hard_bounce_flips_subscriber_and_redacts_error(self):
        import smtplib

        _, sub = _tagged_bill_and_subscriber("bounce@example.org")
        _compose(cadence="weekly")
        exc = smtplib.SMTPRecipientsRefused(
            {"bounce@example.org": (550, b"5.1.1 user unknown")}
        )
        with mock.patch(
            "digests.services.email_client.SmtpDigestEmailClient.send",
            side_effect=exc,
        ):
            _send()
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscriber.STATUS_BOUNCED)
        self.assertIsNotNone(sub.last_bounce_at)
        send = DigestSend.objects.get()
        self.assertEqual(send.status, DigestSend.STATUS_FAILED)
        # The exception text embeds the recipient; the stored error must not.
        self.assertNotIn("bounce@example.org", send.error)
        self.assertIn("SMTPRecipientsRefused", send.error)

    def test_one_failure_does_not_stop_the_batch(self):
        fixtures.bill("CB 200004", action_date=RECENT, tags=["Housing"])
        fixtures.subscriber("first@example.org", issue_areas=["Housing"])
        fixtures.subscriber("second@example.org", issue_areas=["Housing"])
        _compose(cadence="weekly")

        real_send = mail.EmailMultiAlternatives.send
        calls = {"n": 0}

        def flaky(self_, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("relay hiccup for first@example.org")
            return real_send(self_, *args, **kwargs)

        with mock.patch.object(mail.EmailMultiAlternatives, "send", flaky):
            _send()
        self.assertEqual(len(mail.outbox), 1)
        statuses = sorted(DigestSend.objects.values_list("status", flat=True))
        self.assertEqual(statuses, ["failed", "sent"])
        failed = DigestSend.objects.get(status=DigestSend.STATUS_FAILED)
        self.assertNotIn("first@example.org", failed.error)

    def test_intro_slot_renders_from_llm_payload(self):
        # Phase 3 writes llm_payload; the template slot must light up
        # without further changes.
        _, sub = _tagged_bill_and_subscriber("intro@example.org")
        _compose(cadence="weekly")
        DigestSend.objects.update(
            llm_payload={"intro": "Here's your personalized intro."}
        )
        _send()
        self.assertIn("Here's your personalized intro.", mail.outbox[0].body)

    def test_limit(self):
        fixtures.bill("CB 200005", action_date=RECENT, tags=["Housing"])
        fixtures.subscriber("lim1@example.org", issue_areas=["Housing"])
        fixtures.subscriber("lim2@example.org", issue_areas=["Housing"])
        _compose(cadence="weekly")
        _send(limit=1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            DigestSend.objects.filter(status=DigestSend.STATUS_PENDING).count(), 1
        )

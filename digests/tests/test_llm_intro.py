"""Phase 3 intro-batch tests (#238): schema shapes, PII-free request
construction, backend dispatch, and the compose-submit / send-poll paths
with a fake ``DigestLLMClient``.

The design invariant under test throughout: the LLM can only ever ADD to
a digest. Every failure mode — backend off, submit exception, batch in a
terminal state, a subscriber's request errored, the batch outliving the
age cap — must still deliver the templated digest.
"""
import json
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from digests.models import DigestSend
from digests.services.intro_prompt import build_intro_request
from digests.services.llm_client import get_llm_client
from digests.services.llm_schema import compose_schema
from digests.tests import fixtures
from seattle_app.logging_filters import _EMAIL_RE

RECENT = (date.today() - timedelta(days=2)).isoformat()


class FakeLLMClient:
    def __init__(self, batch_id="batch_test_123", status="ended",
                 results=None, submit_error=None, poll_error=None):
        self.batch_id = batch_id
        self.status = status
        self.results = results or {}
        self.submit_error = submit_error
        self.poll_error = poll_error
        self.submitted_requests = None

    def submit_intro_batch(self, requests):
        if self.submit_error:
            raise self.submit_error
        self.submitted_requests = requests
        return self.batch_id

    def batch_status(self, batch_id):
        if self.poll_error:
            raise self.poll_error
        return self.status

    def batch_results(self, batch_id):
        return self.results


def _compose(**kwargs):
    out = StringIO()
    call_command("compose_digests", stdout=out, **kwargs)
    return out.getvalue()


def _send(**kwargs):
    out = StringIO()
    kwargs.setdefault("allow_smtp", True)
    call_command("send_digest_batches", stdout=out, **kwargs)
    return out.getvalue()


def _subscriber_with_news(email="intro@example.org"):
    fixtures.bill(
        "CB 300001", action_date=RECENT, tags=["Housing"], summary="Sum."
    )
    return fixtures.subscriber(email, issue_areas=["Housing"])


def _patch_compose_llm(fake):
    return mock.patch(
        "digests.management.commands.compose_digests.get_llm_client",
        return_value=fake,
    )


def _patch_send_llm(fake):
    return mock.patch(
        "digests.management.commands.send_digest_batches.get_llm_client",
        return_value=fake,
    )


class ComposeSchemaTests(TestCase):
    def test_v1_shape_is_intro_only(self):
        schema = compose_schema(include_blurbs=False)
        self.assertEqual(list(schema["properties"]), ["intro"])
        self.assertEqual(schema["required"], ["intro"])
        self.assertFalse(schema["additionalProperties"])

    def test_blurbs_flip_adds_item_blurbs(self):
        schema = compose_schema(include_blurbs=True)
        self.assertIn("item_blurbs", schema["properties"])
        blurb = schema["properties"]["item_blurbs"]["items"]
        self.assertEqual(blurb["required"], ["item_id", "blurb"])


class IntroRequestTests(TestCase):
    def _request(self):
        rep = fixtures.councilmember("Dan Strauss", "District 6")
        bill = fixtures.bill(
            "CB 300002", action_date=RECENT, tags=["Housing"],
            sponsors=[rep], summary="Plain summary.",
        )
        sub = fixtures.subscriber(
            "very-private@example.org",
            issue_areas=["Housing"],
            followed_reps=[rep],
            followed_bills=[bill],
            district_obj=fixtures.district("6"),
        )
        from digests.services import personalization

        items = personalization.match_items(
            sub.preferences, date.today() - timedelta(days=8)
        )
        return sub, build_intro_request(
            sub.id, sub.preferences, items, "weekly", "claude-test-model"
        )

    def test_no_pii_in_request_body(self):
        # Plan §security 11: nothing email-shaped may reach Anthropic.
        sub, request = self._request()
        serialized = json.dumps(request)
        self.assertNotIn("very-private", serialized)
        self.assertIsNone(_EMAIL_RE.search(serialized))
        self.assertEqual(request["custom_id"], f"sub-{sub.id}")

    def test_request_shape(self):
        _sub, request = self._request()
        params = request["params"]
        self.assertEqual(params["model"], "claude-test-model")
        self.assertNotIn("thinking", params)  # Haiku rejects the param
        self.assertEqual(
            params["system"][0]["cache_control"], {"type": "ephemeral"}
        )
        self.assertEqual(
            params["output_config"]["format"]["schema"],
            compose_schema(include_blurbs=False),
        )
        payload = json.loads(params["messages"][0]["content"])
        self.assertEqual(payload["cadence"], "weekly")
        interests = payload["subscriber_interests"]
        self.assertEqual(interests["issue_areas"], ["Housing"])
        self.assertEqual(interests["followed_councilmembers"], ["Dan Strauss"])
        self.assertEqual(interests["district"], "District 6")
        self.assertEqual(interests["followed_bills"], ["CB 300002"])
        item = payload["items"][0]
        self.assertTrue(item["item_id"].startswith("bill-"))
        self.assertEqual(item["identifier"], "CB 300002")
        self.assertIn("summary", item)
        self.assertIn("matched_because", item)


class BackendDispatchTests(TestCase):
    @override_settings(DIGEST_LLM_BACKEND="none")
    def test_none_backend(self):
        self.assertIsNone(get_llm_client())

    @override_settings(DIGEST_LLM_BACKEND="anthropic", ANTHROPIC_API_KEY="")
    def test_anthropic_without_key_degrades_to_none(self):
        self.assertIsNone(get_llm_client())

    @override_settings(DIGEST_LLM_BACKEND="openai")
    def test_openai_stub_unimplemented(self):
        with self.assertRaises(NotImplementedError):
            get_llm_client()

    @override_settings(DIGEST_LLM_BACKEND="postgres")
    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            get_llm_client()


class ComposeSubmitTests(TestCase):
    def test_batch_id_stamped_on_non_quiet_rows(self):
        _subscriber_with_news()
        quiet = fixtures.subscriber("quiet3@example.org", issue_areas=["Parks & Recreation"])
        fake = FakeLLMClient()
        with _patch_compose_llm(fake):
            out = _compose(cadence="weekly")
        self.assertIn("Submitted intro batch batch_test_123", out)
        with_items = DigestSend.objects.exclude(subscriber=quiet).get()
        self.assertEqual(with_items.compose_batch_id, "batch_test_123")
        quiet_row = DigestSend.objects.get(subscriber=quiet)
        self.assertEqual(quiet_row.compose_batch_id, "")
        # One request, for the non-quiet subscriber only.
        self.assertEqual(len(fake.submitted_requests), 1)

    def test_submit_failure_leaves_rows_batchless(self):
        _subscriber_with_news()
        fake = FakeLLMClient(submit_error=RuntimeError("api down"))
        with _patch_compose_llm(fake):
            out = _compose(cadence="weekly")
        self.assertIn("send without", out)
        self.assertEqual(DigestSend.objects.get().compose_batch_id, "")

    def test_backend_off_skips_submit(self):
        _subscriber_with_news()
        with _patch_compose_llm(None):
            out = _compose(cadence="weekly")
        self.assertIn("LLM backend off", out)
        self.assertEqual(DigestSend.objects.get().compose_batch_id, "")

    def test_dry_run_never_touches_the_client(self):
        _subscriber_with_news()
        fake = FakeLLMClient()
        with _patch_compose_llm(fake):
            _compose(cadence="weekly", dry_run=True)
        self.assertIsNone(fake.submitted_requests)


class SendPollTests(TestCase):
    def _pending_with_batch(self, email="poll@example.org"):
        sub = _subscriber_with_news(email)
        fake_compose = FakeLLMClient()
        with _patch_compose_llm(fake_compose):
            _compose(cadence="weekly")
        return sub, DigestSend.objects.get(subscriber=sub)

    def test_in_flight_batch_keeps_row_pending(self):
        _sub, row = self._pending_with_batch()
        fake = FakeLLMClient(status="in_progress")
        with _patch_send_llm(fake):
            out = _send()
        self.assertIn("1 awaiting", out)
        self.assertEqual(len(mail.outbox), 0)
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_PENDING)

    def test_ended_batch_persists_intro_and_renders_it(self):
        sub, row = self._pending_with_batch()
        fake = FakeLLMClient(
            results={f"sub-{sub.id}": {"intro": "Housing news this week."}}
        )
        with _patch_send_llm(fake):
            _send()
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_SENT)
        self.assertEqual(row.llm_payload, {"intro": "Housing news this week."})
        message = mail.outbox[0]
        self.assertIn("Housing news this week.", message.body)
        self.assertIn("Housing news this week.", message.alternatives[0][0])

    def test_missing_result_sends_without_intro(self):
        _sub, row = self._pending_with_batch()
        fake = FakeLLMClient(results={})  # ended, but nothing for this sub
        with _patch_send_llm(fake):
            _send()
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_SENT)
        self.assertIsNone(row.llm_payload)
        self.assertEqual(len(mail.outbox), 1)

    def test_terminal_batch_state_sends_without_intro(self):
        _sub, row = self._pending_with_batch()
        fake = FakeLLMClient(status="errored")
        with _patch_send_llm(fake):
            _send()
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_SENT)
        self.assertIsNone(row.llm_payload)

    def test_age_cap_sends_without_intro(self):
        _sub, row = self._pending_with_batch()
        DigestSend.objects.filter(pk=row.pk).update(
            created_at=row.created_at - timedelta(hours=7)
        )
        fake = FakeLLMClient(status="in_progress")
        with _patch_send_llm(fake):
            _send()
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_SENT)
        self.assertIsNone(row.llm_payload)
        self.assertEqual(len(mail.outbox), 1)

    def test_transient_poll_error_waits(self):
        _sub, row = self._pending_with_batch()
        fake = FakeLLMClient(poll_error=RuntimeError("503"))
        with _patch_send_llm(fake):
            out = _send()
        self.assertIn("1 awaiting", out)
        row.refresh_from_db()
        self.assertEqual(row.status, DigestSend.STATUS_PENDING)

    def test_batchless_rows_unaffected_by_llm(self):
        # Phase 2 path: no batch id, no client construction, straight send.
        sub = _subscriber_with_news("nobatch@example.org")
        with _patch_compose_llm(None):
            _compose(cadence="weekly")
        with _patch_send_llm(FakeLLMClient(poll_error=RuntimeError("boom"))):
            _send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            DigestSend.objects.get(subscriber=sub).status,
            DigestSend.STATUS_SENT,
        )

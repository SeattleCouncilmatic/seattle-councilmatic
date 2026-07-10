import json

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core import mail
from django.test import TestCase, override_settings

from digests.models import Subscriber, SubscriberPreferences
from digests.services.tokens import PURPOSE_MANAGE, PURPOSE_UNSUBSCRIBE, make_token
from reps.models import District

# The dev settings use DummyCache, under which django-ratelimit is a no-op.
# Rate-limit-sensitive tests (and only those) opt into a real local cache.
LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "digest-tests",
    }
}


def _subscribe(client, payload):
    return client.post(
        "/api/digests/subscribe",
        data=json.dumps(payload),
        content_type="application/json",
    )


class SubscribeTests(TestCase):
    def test_happy_path_creates_pending_and_sends_verification(self):
        response = _subscribe(self.client, {
            "email": "new@example.org",
            "issue_areas": ["Housing"],
            "daily_enabled": True,
        })
        self.assertEqual(response.status_code, 202)
        subscriber = Subscriber.objects.get(email="new@example.org")
        self.assertEqual(subscriber.status, Subscriber.STATUS_PENDING)
        self.assertTrue(subscriber.verification_token)
        prefs = subscriber.preferences
        self.assertEqual(prefs.issue_areas, ["Housing"])
        self.assertTrue(prefs.weekly_enabled)
        self.assertTrue(prefs.daily_enabled)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(subscriber.verification_token, mail.outbox[0].body)
        self.assertIn("/digests/confirm?token=", mail.outbox[0].body)

    def test_honeypot_accepts_and_drops(self):
        response = _subscribe(self.client, {
            "email": "bot@example.org", "website": "http://spam.example",
        })
        self.assertEqual(response.status_code, 202)
        self.assertFalse(Subscriber.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_rejected(self):
        response = _subscribe(self.client, {"email": "not-an-email"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Subscriber.objects.exists())

    def test_unknown_issue_area_rejected(self):
        response = _subscribe(self.client, {
            "email": "tags@example.org", "issue_areas": ["Skateboards"],
        })
        self.assertEqual(response.status_code, 400)

    def test_unknown_rep_id_rejected(self):
        response = _subscribe(self.client, {
            "email": "reps@example.org",
            "followed_rep_ids": ["ocd-person/00000000-0000-0000-0000-000000000000"],
        })
        self.assertEqual(response.status_code, 400)

    def test_district_preference_applied(self):
        square = MultiPolygon(Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))))
        district = District.objects.create(number="3", name="District 3", geometry=square)
        response = _subscribe(self.client, {
            "email": "d3@example.org", "district_id": district.pk,
        })
        self.assertEqual(response.status_code, 202)
        subscriber = Subscriber.objects.get(email="d3@example.org")
        self.assertEqual(subscriber.preferences.district, district)

    def test_active_subscriber_gets_silent_202_and_no_email(self):
        Subscriber.objects.create(
            email="already@example.org", status=Subscriber.STATUS_ACTIVE
        )
        response = _subscribe(self.client, {"email": "Already@Example.org"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            Subscriber.objects.get(email="already@example.org").status,
            Subscriber.STATUS_ACTIVE,
        )

    def test_pending_resubscribe_rotates_token_and_resends(self):
        _subscribe(self.client, {"email": "again@example.org"})
        first_token = Subscriber.objects.get(email="again@example.org").verification_token
        _subscribe(self.client, {"email": "again@example.org"})
        second_token = Subscriber.objects.get(email="again@example.org").verification_token
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(len(mail.outbox), 2)


@override_settings(CACHES=LOCMEM_CACHE)
class SubscribeRateLimitTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_same_email_limited_to_one_per_hour(self):
        first = _subscribe(self.client, {"email": "limit@example.org"})
        self.assertEqual(first.status_code, 202)
        second = _subscribe(self.client, {"email": "limit@example.org"})
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "3600")

    def test_ip_limited_to_five_per_hour(self):
        for i in range(5):
            response = _subscribe(self.client, {"email": f"user{i}@example.org"})
            self.assertEqual(response.status_code, 202, f"request {i} unexpectedly limited")
        sixth = _subscribe(self.client, {"email": "user5@example.org"})
        self.assertEqual(sixth.status_code, 429)


class ManageLinkRequestTests(TestCase):
    def _request(self, email):
        return self.client.post(
            "/api/digests/manage-link",
            data=json.dumps({"email": email}),
            content_type="application/json",
        )

    def test_active_subscriber_gets_manage_link(self):
        Subscriber.objects.create(
            email="linkme@example.org", status=Subscriber.STATUS_ACTIVE
        )
        response = self._request("LinkMe@Example.org")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/digests/manage?token=", mail.outbox[0].body)

    def test_pending_subscriber_gets_verification_resend(self):
        Subscriber.objects.create(
            email="stillpending@example.org",
            status=Subscriber.STATUS_PENDING,
            verification_token="tok-pending-123",
        )
        response = self._request("stillpending@example.org")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/digests/confirm?token=tok-pending-123", mail.outbox[0].body)

    def test_unknown_email_same_202_no_email(self):
        # Enumeration guard: the response is indistinguishable from success.
        response = self._request("nobody@example.org")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)

    def test_unsubscribed_gets_nothing(self):
        Subscriber.objects.create(
            email="gone@example.org", status=Subscriber.STATUS_UNSUBSCRIBED
        )
        response = self._request("gone@example.org")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_rejected(self):
        self.assertEqual(self._request("not-an-email").status_code, 400)

    @override_settings(CACHES=LOCMEM_CACHE)
    def test_rate_limited_per_email(self):
        from django.core.cache import cache
        cache.clear()
        Subscriber.objects.create(
            email="ratelimit@example.org", status=Subscriber.STATUS_ACTIVE
        )
        self.assertEqual(self._request("ratelimit@example.org").status_code, 202)
        second = self._request("ratelimit@example.org")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "3600")


class ConfirmTests(TestCase):
    def test_confirm_activates_and_clears_token(self):
        _subscribe(self.client, {"email": "confirm@example.org"})
        subscriber = Subscriber.objects.get(email="confirm@example.org")
        response = self.client.get(f"/digests/confirm?token={subscriber.verification_token}")
        self.assertEqual(response.status_code, 200)
        subscriber.refresh_from_db()
        self.assertEqual(subscriber.status, Subscriber.STATUS_ACTIVE)
        self.assertIsNone(subscriber.verification_token)
        self.assertIsNotNone(subscriber.verified_at)

    def test_reused_or_unknown_token_is_404(self):
        _subscribe(self.client, {"email": "reuse@example.org"})
        token = Subscriber.objects.get(email="reuse@example.org").verification_token
        self.client.get(f"/digests/confirm?token={token}")
        second_click = self.client.get(f"/digests/confirm?token={token}")
        self.assertEqual(second_click.status_code, 404)
        self.assertEqual(self.client.get("/digests/confirm?token=nope").status_code, 404)


class ManageAndPreferencesTests(TestCase):
    def setUp(self):
        self.subscriber = Subscriber.objects.create(
            email="manage@example.org", status=Subscriber.STATUS_ACTIVE
        )
        SubscriberPreferences.objects.create(subscriber=self.subscriber)

    def _open_manage_session(self):
        token = make_token(self.subscriber, PURPOSE_MANAGE)
        return self.client.get(f"/digests/manage?token={token}")

    def test_manage_link_sets_session_and_redirects(self):
        response = self._open_manage_session()
        self.assertRedirects(response, "/digests/preferences", fetch_redirect_response=False)
        self.assertEqual(
            self.client.session.get("digest_subscriber_id"), self.subscriber.pk
        )

    def test_manage_with_bad_token_is_404(self):
        self.assertEqual(self.client.get("/digests/manage?token=1.junk").status_code, 404)

    def test_preferences_requires_session(self):
        self.assertEqual(self.client.get("/api/digests/preferences").status_code, 401)

    def test_preferences_get_returns_masked_email_and_prefs(self):
        self._open_manage_session()
        response = self.client.get("/api/digests/preferences")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["email_masked"], "m***@example.org")
        self.assertNotIn("manage@example.org", json.dumps(data))
        self.assertTrue(data["weekly_enabled"])
        self.assertIn("/digests/unsubscribe?token=", data["unsubscribe_url"])

    def test_preferences_post_updates(self):
        self._open_manage_session()
        response = self.client.post(
            "/api/digests/preferences",
            data=json.dumps({"weekly_enabled": False, "issue_areas": ["Labor"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        prefs = SubscriberPreferences.objects.get(subscriber=self.subscriber)
        self.assertFalse(prefs.weekly_enabled)
        self.assertEqual(prefs.issue_areas, ["Labor"])

    def test_preferences_requests_slide_session_expiry(self):
        # Every authenticated call resets the 1-hour clock so the session
        # can't lapse mid-edit.
        self._open_manage_session()
        session = self.client.session
        session.set_expiry(10)  # nearly-expired
        session.save()
        self.client.get("/api/digests/preferences")
        self.assertGreater(self.client.session.get_expiry_age(), 3000)

    def test_preferences_post_invalid_tag_rejected(self):
        self._open_manage_session()
        response = self.client.post(
            "/api/digests/preferences",
            data=json.dumps({"issue_areas": ["Skateboards"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class UnsubscribeTests(TestCase):
    def setUp(self):
        self.subscriber = Subscriber.objects.create(
            email="unsub@example.org", status=Subscriber.STATUS_ACTIVE
        )
        self.token = make_token(self.subscriber, PURPOSE_UNSUBSCRIBE)

    def test_get_renders_confirmation_page(self):
        response = self.client.get(f"/digests/unsubscribe?token={self.token}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "u***@example.org")

    def test_post_unsubscribes(self):
        response = self.client.post("/digests/unsubscribe", {"token": self.token})
        self.assertEqual(response.status_code, 200)
        self.subscriber.refresh_from_db()
        self.assertEqual(self.subscriber.status, Subscriber.STATUS_UNSUBSCRIBED)
        self.assertIsNotNone(self.subscriber.unsubscribed_at)

    def test_one_click_post_returns_plain_200(self):
        # RFC 8058: mail providers POST List-Unsubscribe=One-Click to the URL.
        response = self.client.post(
            f"/digests/unsubscribe?token={self.token}",
            {"List-Unsubscribe": "One-Click"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.subscriber.refresh_from_db()
        self.assertEqual(self.subscriber.status, Subscriber.STATUS_UNSUBSCRIBED)

    def test_delete_now_removes_row(self):
        response = self.client.post(
            "/digests/unsubscribe", {"token": self.token, "delete_now": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Subscriber.objects.filter(pk=self.subscriber.pk).exists())

    def test_bad_token_is_404(self):
        self.assertEqual(self.client.post("/digests/unsubscribe", {"token": "1.junk"}).status_code, 404)


class OptionsTests(TestCase):
    def test_options_lists_vocabulary(self):
        response = self.client.get("/api/digests/options")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Housing", data["issue_areas"])
        self.assertEqual(data["reps"], [])       # no council members in test DB
        self.assertEqual(data["districts"], [])

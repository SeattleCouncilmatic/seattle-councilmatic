from django.test import TestCase

from digests.models import Subscriber
from digests.services.tokens import (
    PURPOSE_MANAGE,
    PURPOSE_UNSUBSCRIBE,
    make_token,
    verify_token,
)


class TokenRoundTripTests(TestCase):
    def setUp(self):
        self.subscriber = Subscriber.objects.create(email="tokens@example.org")

    def test_round_trip_both_purposes(self):
        for purpose in (PURPOSE_MANAGE, PURPOSE_UNSUBSCRIBE):
            token = make_token(self.subscriber, purpose)
            self.assertEqual(verify_token(token, purpose), self.subscriber)

    def test_purpose_separation(self):
        # An unsubscribe link must not authenticate the preferences flow.
        token = make_token(self.subscriber, PURPOSE_UNSUBSCRIBE)
        self.assertIsNone(verify_token(token, PURPOSE_MANAGE))

    def test_tampered_signature_rejected(self):
        token = make_token(self.subscriber, PURPOSE_MANAGE)
        raw_id, sig = token.split(".", 1)
        flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
        self.assertIsNone(verify_token(f"{raw_id}.{flipped}", PURPOSE_MANAGE))

    def test_version_bump_revokes_outstanding_tokens(self):
        token = make_token(self.subscriber, PURPOSE_MANAGE)
        self.subscriber.unsubscribe_token_version += 1
        self.subscriber.save()
        self.assertIsNone(verify_token(token, PURPOSE_MANAGE))
        # Freshly minted tokens work again.
        fresh = make_token(self.subscriber, PURPOSE_MANAGE)
        self.assertEqual(verify_token(fresh, PURPOSE_MANAGE), self.subscriber)

    def test_garbage_tokens_rejected(self):
        for garbage in ("", "no-dot", "notanint.abcdef", "999999.deadbeef", None):
            self.assertIsNone(verify_token(garbage, PURPOSE_MANAGE))

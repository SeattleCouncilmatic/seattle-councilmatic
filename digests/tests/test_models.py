from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from digests.models import Subscriber, validate_issue_areas


class SubscriberModelTests(TestCase):
    def test_email_normalized_lowercase_on_save(self):
        s = Subscriber.objects.create(email="  MixedCase@Example.ORG ")
        self.assertEqual(s.email, "mixedcase@example.org")

    def test_uniqueness_is_case_insensitive_via_normalization(self):
        Subscriber.objects.create(email="dup@example.org")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subscriber.objects.create(email="DUP@EXAMPLE.ORG")

    def test_mark_unsubscribed(self):
        s = Subscriber.objects.create(
            email="bye@example.org", status=Subscriber.STATUS_ACTIVE
        )
        s.mark_unsubscribed()
        s.refresh_from_db()
        self.assertEqual(s.status, Subscriber.STATUS_UNSUBSCRIBED)
        self.assertIsNotNone(s.unsubscribed_at)

    def test_str_never_contains_email(self):
        # __str__ shows up in logs and admin — id only, never the address.
        s = Subscriber.objects.create(email="secret@example.org")
        self.assertNotIn("secret", str(s))
        self.assertNotIn("@", str(s))


class IssueAreaValidatorTests(TestCase):
    def test_accepts_known_tags(self):
        validate_issue_areas(["Housing", "Transportation"])  # no raise

    def test_rejects_unknown_tags(self):
        with self.assertRaises(ValidationError):
            validate_issue_areas(["Housing", "Skateboards"])

    def test_rejects_non_list(self):
        with self.assertRaises(ValidationError):
            validate_issue_areas("Housing")

    def test_accepts_empty_list(self):
        validate_issue_areas([])  # no raise

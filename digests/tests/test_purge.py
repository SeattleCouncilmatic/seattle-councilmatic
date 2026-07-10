from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from digests.models import Subscriber


class PurgeCommandTests(TestCase):
    def test_purges_only_expired_unsubscribed(self):
        old = Subscriber.objects.create(
            email="old@example.org",
            status=Subscriber.STATUS_UNSUBSCRIBED,
            unsubscribed_at=timezone.now() - timedelta(days=31),
        )
        fresh = Subscriber.objects.create(
            email="fresh@example.org",
            status=Subscriber.STATUS_UNSUBSCRIBED,
            unsubscribed_at=timezone.now() - timedelta(days=5),
        )
        active = Subscriber.objects.create(
            email="active@example.org", status=Subscriber.STATUS_ACTIVE
        )

        call_command("purge_unsubscribed", "--dry-run", stdout=StringIO())
        self.assertEqual(Subscriber.objects.count(), 3)

        out = StringIO()
        call_command("purge_unsubscribed", stdout=out)
        remaining = set(Subscriber.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {fresh.pk, active.pk})
        self.assertFalse(Subscriber.objects.filter(pk=old.pk).exists())
        # Command output references ids, never addresses.
        self.assertNotIn("@", out.getvalue())

    def test_days_flag_narrows_window(self):
        Subscriber.objects.create(
            email="week@example.org",
            status=Subscriber.STATUS_UNSUBSCRIBED,
            unsubscribed_at=timezone.now() - timedelta(days=10),
        )
        call_command("purge_unsubscribed", "--days", "7", stdout=StringIO())
        self.assertEqual(Subscriber.objects.count(), 0)

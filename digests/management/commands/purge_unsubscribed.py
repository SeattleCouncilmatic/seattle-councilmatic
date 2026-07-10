"""Hard-delete subscriber rows N days after unsubscribe (#231).

Right-to-delete hygiene: an unsubscribed row is dead weight PII. The
30-day default window exists so a quick resubscribe finds preferences
intact; after that the row (and its cascade: preferences, send log) is
gone. Immediate deletion is available to subscribers on the unsubscribe
page itself; this command is the scheduled backstop.

Usage:
    python manage.py purge_unsubscribed             # delete, 30-day window
    python manage.py purge_unsubscribed --days 7
    python manage.py purge_unsubscribed --dry-run   # count only
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from digests.models import Subscriber


class Command(BaseCommand):
    help = "Hard-delete subscribers N days (default 30) after unsubscribe."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=30,
            help="Retention window in days after unsubscribe (default 30).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be deleted; don't delete.",
        )

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        candidates = Subscriber.objects.filter(
            status=Subscriber.STATUS_UNSUBSCRIBED,
            unsubscribed_at__lt=cutoff,
        )
        count = candidates.count()
        if opts["dry_run"]:
            self.stdout.write(
                f"[dry-run] {count} subscriber(s) unsubscribed before "
                f"{cutoff.isoformat()} would be deleted."
            )
            return
        # ids logged, never emails.
        ids = list(candidates.values_list("pk", flat=True))
        candidates.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {count} subscriber(s): {ids}"
        ))

"""Compose personalized digests: run the match queries and snapshot the
results into pending ``DigestSend`` rows (Phase 2, #235).

For every active subscriber with the cadence enabled, matches the window's
council news against their preferences (see ``services/personalization``)
and creates a ``DigestSend(status=pending)`` carrying the
``matched_item_ids`` snapshot. ``send_digest_batches`` renders and delivers
pending rows — the row is the compose→send handoff, no state files.

Phase 3 adds the Anthropic Batch submit here (intro paragraph per
subscriber); the pending rows are already shaped for it (``llm_payload``
stays NULL until then).

Zero-match handling per the plan: weekly subscribers still get a short
"quiet week" digest (the cadence promise is a weekly email); daily
subscribers are skipped entirely (daily is "when there's news").

Usage:
    python manage.py compose_digests --cadence weekly
    python manage.py compose_digests --cadence daily --dry-run
    python manage.py compose_digests --cadence weekly --limit 3
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from digests.models import DigestSend, Subscriber
from digests.services import personalization


class Command(BaseCommand):
    help = "Match subscriber preferences against recent council activity and create pending DigestSend rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cadence",
            required=True,
            choices=[DigestSend.CADENCE_WEEKLY, DigestSend.CADENCE_DAILY],
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report per-subscriber match counts without creating rows.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max subscribers to compose for (testing).",
        )
        parser.add_argument(
            "--since",
            default=None,
            help="Override the news-window start (YYYY-MM-DD). QA knob for "
            "composing against a dev DB whose last scrape predates the "
            "cadence window.",
        )

    def handle(self, *args, **opts):
        cadence = opts["cadence"]
        now = timezone.now()
        today = timezone.localdate()
        since_override = (
            date.fromisoformat(opts["since"]) if opts["since"] else None
        )

        cadence_flag = (
            "preferences__weekly_enabled"
            if cadence == DigestSend.CADENCE_WEEKLY
            else "preferences__daily_enabled"
        )
        candidates = (
            Subscriber.objects.filter(
                status=Subscriber.STATUS_ACTIVE, **{cadence_flag: True}
            )
            .select_related("preferences")
            .order_by("id")
        )
        if opts["limit"] is not None:
            candidates = candidates[: opts["limit"]]

        composed = skipped_dedup = skipped_quiet = 0
        for subscriber in candidates:
            # One digest per cadence per day. A pending row of any age also
            # blocks — composing on top of an unsent digest would double-send
            # once send_digest_batches catches up.
            already = subscriber.sends.filter(cadence=cadence).filter(
                Q(status=DigestSend.STATUS_PENDING) | Q(sent_at__date=today)
            )
            if already.exists():
                skipped_dedup += 1
                continue

            since = since_override or personalization.window_start(
                cadence, subscriber, now
            )
            items = personalization.match_items(subscriber.preferences, since)

            if not items and cadence == DigestSend.CADENCE_DAILY:
                skipped_quiet += 1
                continue

            if opts["dry_run"]:
                self.stdout.write(
                    f"[dry-run] subscriber {subscriber.id}: {len(items)} item(s) "
                    f"since {since.isoformat()}"
                )
            else:
                DigestSend.objects.create(
                    subscriber=subscriber,
                    cadence=cadence,
                    matched_item_ids=personalization.snapshot(items),
                    item_count=len(items),
                )
            composed += 1

        prefix = "[dry-run] Would compose" if opts["dry_run"] else "Composed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {composed} {cadence} digest(s); "
                f"{skipped_dedup} deduped, {skipped_quiet} skipped with no news."
            )
        )

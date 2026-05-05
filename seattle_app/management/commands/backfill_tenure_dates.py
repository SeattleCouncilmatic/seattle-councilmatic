"""Backfill `Membership.start_date` for current Seattle City Council
members from the hardcoded dict in `seattle/tenures.py`.

The Legistar people endpoint doesn't expose tenure dates. Both this
command and the live `SeattlePersonScraper` (`seattle/people.py`) read
the same source-of-truth dict so a re-scrape doesn't wipe what this
command writes.

Use this command for the *immediate* effect — when you've added a new
entry to `tenures.py` and want it on the rep page now without waiting
for the next daily scrape.

    python manage.py backfill_tenure_dates
    python manage.py backfill_tenure_dates --dry-run

Idempotent — re-running is a no-op when every Membership row already
matches the dict.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from opencivicdata.legislative.models import Bill  # noqa: F401  (forces app registry warmup)
from opencivicdata.core.models import Person, Membership

from seattle.tenures import COUNCIL_TENURE_START


class Command(BaseCommand):
    help = "Set Membership.start_date for current councilmembers from seattle/tenures.py."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change but don't write to the DB.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        applied = 0
        skipped_no_date = 0
        skipped_unchanged = 0
        not_found = 0

        for (name, label), start_date in COUNCIL_TENURE_START.items():
            if not start_date:
                self.stdout.write(f"  SKIP   {name} ({label}) — no date in tenures.py yet")
                skipped_no_date += 1
                continue

            # Match by person name + membership label. The combination is
            # unique among current memberships; using both guards against
            # name collisions across former and current holders of the
            # same seat.
            membership = (
                Membership.objects
                .select_related("person", "organization")
                .filter(
                    person__name=name,
                    label=label,
                    organization__name="Seattle City Council",
                )
                .first()
            )
            if not membership:
                self.stdout.write(self.style.WARNING(
                    f"  MISS   {name} ({label}) — no Membership row matches"
                ))
                not_found += 1
                continue

            if membership.start_date == start_date:
                skipped_unchanged += 1
                continue

            old = membership.start_date or "(unset)"
            self.stdout.write(f"  SET    {name} ({label}): {old} → {start_date}")
            if not dry:
                membership.start_date = start_date
                membership.save(update_fields=["start_date"])
            applied += 1

        verb = "would update" if dry else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb} {applied} Membership rows. "
            f"{skipped_unchanged} unchanged, {skipped_no_date} pending verification, "
            f"{not_found} not found."
        ))

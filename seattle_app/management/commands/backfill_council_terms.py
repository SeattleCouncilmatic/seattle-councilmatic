"""Backfill ``Membership.start_date``/``end_date`` for current Seattle
City Council members using term data from Legistar's Department Detail
page.

The OCD scraper populates these dates for some seats and leaves them
blank for others (especially mid-term replacements like Juarez, who
returned to fill out Cathy Moore's term in 2025, and Foster/Lin, who
were sworn in late 2025-early 2026). Without start dates, the rep-
summary prompt has to degrade to "currently serving" wording — see
``reps.stats._tenure_context``.

Source of truth: Legistar Department Detail page for "City Council"
(Department ID 28340). The page lists every current member with
their current term's start and end dates. Hardcoded here rather than
scraped at runtime — terms change rarely (every 2-4 years per seat),
and a hardcoded backfill is reproducible across environments.

Re-run this command whenever a council member is sworn in, resigns,
or is replaced. Idempotent — only writes a date when the existing
value is empty (won't clobber the OCD scraper's populated dates).

Usage:
    python manage.py backfill_council_terms
    python manage.py backfill_council_terms --dry-run
    python manage.py backfill_council_terms --force  # overwrite existing
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from opencivicdata.core.models import Person


# Source: https://seattle.legistar.com/DepartmentDetail.aspx?ID=28340&GUID=E46BCBAD-A6DB-4A4B-AC5E-D2D659A4F94D&Mode=MainBody
# Last fetched 2026-05-11. (start_date, end_date) per the Legistar
# "current term" columns.
COUNCIL_TERMS: dict[str, tuple[str, str]] = {
    "Joy Hollingsworth":     ("2024-01-02", "2027-12-31"),
    "Alexis Mercedes Rinck": ("2024-11-26", "2029-12-31"),
    "Dan Strauss":           ("2020-01-01", "2027-12-31"),
    "Debora Juarez":         ("2025-07-28", "2026-11-24"),
    "Dionne Foster":         ("2026-01-01", "2029-12-31"),
    "Eddie Lin":             ("2025-11-25", "2027-12-31"),
    "Maritza Rivera":        ("2024-01-02", "2027-12-31"),
    "Rob Saka":              ("2024-01-02", "2027-12-31"),
    "Robert Kettle":         ("2024-01-02", "2027-12-31"),
}


_COUNCIL_ORG_NAME = "Seattle City Council"


class Command(BaseCommand):
    help = (
        "Backfill Membership.start_date/end_date for current council "
        "members using Legistar's Department Detail term data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing populated dates (defaults to skip).",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        force = opts["force"]
        today = date.today().isoformat()

        n_updated = 0
        n_skipped = 0
        n_missing = 0

        for name, (legistar_start, legistar_end) in COUNCIL_TERMS.items():
            person = Person.objects.filter(name=name).first()
            if not person:
                self.stderr.write(self.style.WARNING(
                    f"  {name}: no Person row; skipping"
                ))
                n_missing += 1
                continue

            # Active membership = end_date in the future or unset.
            # When a person has both a populated and an unpopulated
            # row for the same seat, prefer the populated one — that's
            # the OCD scraper's canonical record. Sort by populated-
            # start-date DESC (matches reps.stats._tenure_context).
            candidates = list(
                person.memberships
                .filter(organization__name=_COUNCIL_ORG_NAME)
                .filter(Q(end_date="") | Q(end_date__gte=today))
            )
            if not candidates:
                self.stderr.write(self.style.WARNING(
                    f"  {name}: no active Seattle City Council membership; skipping"
                ))
                n_missing += 1
                continue

            candidates.sort(
                key=lambda m: (1 if m.start_date else 0, m.start_date or ""),
                reverse=True,
            )
            membership = candidates[0]

            updates: list[str] = []
            if not membership.start_date or force:
                if membership.start_date != legistar_start:
                    updates.append(f"start_date {membership.start_date!r}->{legistar_start}")
                    membership.start_date = legistar_start
            if not membership.end_date or force:
                if membership.end_date != legistar_end:
                    updates.append(f"end_date {membership.end_date!r}->{legistar_end}")
                    membership.end_date = legistar_end

            if not updates:
                self.stdout.write(f"  {name}: already populated; skipping")
                n_skipped += 1
                continue

            self.stdout.write(
                f"  {name}: " + ", ".join(updates)
            )
            if not dry:
                with transaction.atomic():
                    membership.save(update_fields=["start_date", "end_date"])
                n_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone (dry-run={dry}). Updated: {n_updated}. "
            f"Skipped (already populated): {n_skipped}. Missing: {n_missing}."
        ))

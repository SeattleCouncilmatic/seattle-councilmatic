"""Merge duplicate council-seat Memberships caused by pupa's
start-date-aware import logic.

Pupa's `MembershipImporter.get_object` uses `start_date` as part of
its uniqueness key. When a scraper that previously didn't pass
`start_date` starts passing one, pupa can't find the existing
dateless row → creates a new dated one → duplicate. The scraper has
since been fixed to never pass start_date (admin owns that field
now), but any prod DB that ran the dated-scrape version once already
has duplicates that need cleaning up.

For each (person, organization, label, role) group with > 1 row:
- Keep the row with `start_date` set (or any date set, vs none)
- If multiple rows have dates, keep the most-recently-updated one
- If no row has dates, keep the most-recently-updated one
- Delete the rest

Idempotent — re-running on a clean DB does nothing.

    python manage.py dedup_council_memberships
    python manage.py dedup_council_memberships --dry-run
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from opencivicdata.core.models import Membership


class Command(BaseCommand):
    help = "Merge duplicate council-seat Membership rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted; don't write to the DB.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]

        # Group all memberships by (person_id, organization_id, label, role).
        # That's the natural identity for "the same membership."
        groups: dict[tuple, list[Membership]] = defaultdict(list)
        for m in Membership.objects.select_related("person", "organization"):
            key = (m.person_id, m.organization_id, m.label, m.role)
            groups[key].append(m)

        total_groups = len(groups)
        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}

        if not dup_groups:
            self.stdout.write(self.style.SUCCESS(
                f"No duplicates found across {total_groups} membership groups."
            ))
            return

        deleted_count = 0
        for key, rows in dup_groups.items():
            person = rows[0].person
            org = rows[0].organization
            label = rows[0].label
            role = rows[0].role
            person_name = person.name if person else "(no person)"
            org_name = org.name if org else "(no org)"

            # Keep the row that's most likely the canonical one:
            #   1. Has start_date set (vs not)
            #   2. Tiebreak by most-recent updated_at
            rows.sort(
                key=lambda r: (bool(r.start_date or r.end_date), r.updated_at),
                reverse=True,
            )
            keep = rows[0]
            drop = rows[1:]

            self.stdout.write(
                f"  GROUP  {person_name:30s}  {org_name[:35]:35s}  {label!r:14s}  {role!r}"
            )
            self.stdout.write(
                f"    KEEP {keep.id[-8:]}  start={keep.start_date or '(unset)':>10s}  "
                f"end={keep.end_date or '(unset)':>10s}  updated={keep.updated_at}"
            )
            for r in drop:
                self.stdout.write(
                    f"    DROP {r.id[-8:]}  start={r.start_date or '(unset)':>10s}  "
                    f"end={r.end_date or '(unset)':>10s}  updated={r.updated_at}"
                )
                if not dry:
                    r.delete()
                deleted_count += 1

        verb = "would delete" if dry else "deleted"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb} {deleted_count} duplicate Membership row(s) "
            f"across {len(dup_groups)} group(s)."
        ))

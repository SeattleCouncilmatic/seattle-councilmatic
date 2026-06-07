"""Scrape committee scope + regular meeting schedule from each committee's
seattle.gov page and upsert ``CommitteeProfile`` rows.

The OCD scrape gives us committees (name, roster, source URL) but not the
"Committee Scope:" remit or the "Committee regular meeting days and time:"
line that seattle.gov publishes. The committee LLM summary
(``summarize_committees``) uses both as ground truth, so we persist the raw
text here and let the summary pipeline re-run cheaply against it.

Idempotent — re-running UPSERTs by ``organization_id``. Scope/schedule change
rarely (committee reorganizations), so weekly cadence is plenty.

Usage::

    python manage.py scrape_committee_info             # all committees
    python manage.py scrape_committee_info --dry-run   # report, no DB writes
    python manage.py scrape_committee_info --committee public-safety
"""
from __future__ import annotations

import time

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from seattle_app.models import CommitteeProfile
from seattle_app.services.committee_scrape import extract_committee_info

_REQUEST_DELAY_SECONDS = 2


class Command(BaseCommand):
    help = "Scrape committee scope + meeting schedule from seattle.gov into CommitteeProfile."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--committee", default=None,
            help="Limit to one committee — slug ('public-safety') or exact name.",
        )

    def handle(self, *args, **options):
        from seattle_app.api_views import _committee_orgs

        dry = options["dry_run"]
        only = options.get("committee")

        orgs = list(_committee_orgs().prefetch_related("sources").order_by("name"))
        if only:
            orgs = [o for o in orgs if slugify(o.name) == only or o.name == only]

        self.stdout.write(
            f"Scraping scope/schedule for {len(orgs)} committee(s) (dry-run={dry})."
        )

        n_updated = n_skipped = n_errors = 0
        for org in orgs:
            sources = list(org.sources.all())
            url = sources[0].url if sources else None
            if not url:
                self.stdout.write(self.style.NOTICE(
                    f"  {org.name}: no source URL; skipping"
                ))
                n_skipped += 1
                continue

            try:
                resp = requests.get(url, timeout=15)
            except requests.RequestException as e:
                self.stderr.write(self.style.WARNING(
                    f"  {org.name}: fetch failed ({type(e).__name__}: {e})"
                ))
                n_errors += 1
                continue

            if resp.status_code != 200:
                self.stdout.write(self.style.NOTICE(
                    f"  {org.name}: HTTP {resp.status_code} at {url}; skipping"
                ))
                n_skipped += 1
                time.sleep(_REQUEST_DELAY_SECONDS)
                continue

            scope, schedule = extract_committee_info(resp.text)
            if not scope and not schedule:
                self.stderr.write(self.style.WARNING(
                    f"  {org.name}: no scope/schedule found at {url}"
                ))
                n_skipped += 1
                time.sleep(_REQUEST_DELAY_SECONDS)
                continue

            self.stdout.write(
                f"  {org.name}: scope {len(scope):,} chars | schedule "
                f"{schedule or '(none)'!r}"
            )

            if not dry:
                with transaction.atomic():
                    CommitteeProfile.objects.update_or_create(
                        organization=org,
                        defaults={
                            "scope": scope,
                            "meeting_schedule": schedule,
                            "source_url": url,
                        },
                    )
                n_updated += 1

            time.sleep(_REQUEST_DELAY_SECONDS)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Updated: {n_updated}. Skipped: {n_skipped}. Errors: {n_errors}."
        ))

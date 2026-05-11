"""Scrape biographical prose from seattle.gov About pages and upsert
``RepBio`` rows for current council members.

Background — issue #147 phase 1a
================================

The rep-summary LLM pipeline needs bio prose (education, professional
background, prior public service) for each councilmember. seattle.gov
already publishes these on per-member About pages
(``/about-<firstname>``). We persist the raw prose so the summary
pipeline can be re-run cheaply against the same source text without
re-scraping each time.

Bio shape varies across reps — some bios are a single paragraph,
others span 4–5 — so we keep the prose as one ``RepBio.bio`` text
field and let the LLM extract structured pieces (education, prior
roles, etc.) at synthesis time.

Idempotent — re-running upserts by ``person_id``. Safe to schedule at
monthly cadence.

Usage
=====

::

    python manage.py scrape_rep_bios            # all current members
    python manage.py scrape_rep_bios --dry-run  # report, no DB writes
    python manage.py scrape_rep_bios --person "Joy Hollingsworth"

Pages that don't yield a bio (404, no qualifying paragraphs, etc.)
log a warning and continue — the summary pipeline downstream marks
those reps as "bio pending" rather than blocking.
"""

from __future__ import annotations

import time

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from opencivicdata.core.models import Person

from reps.models import RepBio
from seattle.people import ABOUT_PAGE_SLUGS, extract_bio, profile_slug


_HOST = "https://www.seattle.gov"
# About pages are a subpath under each member's profile, e.g.
# /council/members/rob-saka/about-rob — see seattle/people.py.
_MEMBERS_PATH_PREFIX = "/council/members"
_REQUEST_DELAY_SECONDS = 2


def _about_page_url(person_name: str) -> str | None:
    """seattle.gov About-page URL for a councilmember, or None if
    we don't have an About-page slug mapping for them."""
    about_slug = ABOUT_PAGE_SLUGS.get(person_name)
    if not about_slug:
        return None
    return f"{_HOST}{_MEMBERS_PATH_PREFIX}/{profile_slug(person_name)}/{about_slug}"


class Command(BaseCommand):
    help = "Scrape councilmember bios from seattle.gov About pages into RepBio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change; don't write to the DB.",
        )
        parser.add_argument(
            "--person",
            help="Limit to a single Person by exact name match.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        only = options.get("person")

        # Current council members are Persons with a `City Council
        # profile` link AND an About-page slug we know about. The
        # latter filter excludes former members whose About page URL
        # may redirect to a successor.
        qs = Person.objects.filter(links__note="City Council profile").distinct()
        if only:
            qs = qs.filter(name=only)

        total = qs.count()
        self.stdout.write(f"Scraping bios for up to {total} councilmember(s) (dry-run={dry}).")

        n_updated = 0
        n_skipped = 0
        n_errors = 0

        for person in qs:
            url = _about_page_url(person.name)
            if not url:
                self.stdout.write(self.style.NOTICE(
                    f"  {person.name}: no About-page slug; skipping"
                ))
                n_skipped += 1
                continue

            try:
                # allow_redirects=False so a former member whose About
                # page redirects to their successor doesn't silently
                # overwrite with the wrong bio.
                resp = requests.get(url, timeout=10, allow_redirects=False)
            except requests.RequestException as e:
                self.stderr.write(self.style.WARNING(
                    f"  {person.name}: fetch failed ({type(e).__name__}: {e})"
                ))
                n_errors += 1
                continue

            if resp.status_code != 200:
                self.stdout.write(self.style.NOTICE(
                    f"  {person.name}: HTTP {resp.status_code} at {url}; skipping"
                ))
                n_skipped += 1
                time.sleep(_REQUEST_DELAY_SECONDS)
                continue

            bio = extract_bio(resp.text)
            if not bio:
                self.stderr.write(self.style.WARNING(
                    f"  {person.name}: no bio prose found at {url}"
                ))
                n_skipped += 1
                time.sleep(_REQUEST_DELAY_SECONDS)
                continue

            self.stdout.write(
                f"  {person.name}: {len(bio):,} chars from {url}"
            )

            if not dry:
                with transaction.atomic():
                    RepBio.objects.update_or_create(
                        person=person,
                        defaults={"bio": bio, "source_url": url},
                    )
                n_updated += 1

            time.sleep(_REQUEST_DELAY_SECONDS)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Updated: {n_updated}. Skipped: {n_skipped}. Errors: {n_errors}."
        ))

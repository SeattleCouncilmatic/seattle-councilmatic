"""Backfill `core.PersonContactDetail` rows for current/former Seattle
City Council members from their per-member seattle.gov profile pages.

The original pupa scrape only emitted a guessed
`firstname.lastname@seattle.gov` email per member. The per-member
detail page also exposes phone, fax, and office/mailing addresses (and
the canonical email capitalization, which matters for multi-name
members like Alexis Mercedes Rinck where the guess and the real
mailbox differ).

This command walks every Person that has a `City Council profile`
link, fetches the URL, parses the Contact Us tile, and upserts contact
detail rows. Idempotent — re-running won't duplicate.

    python manage.py backfill_council_contacts
    python manage.py backfill_council_contacts --dry-run
"""

from __future__ import annotations

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from opencivicdata.core.models import Person

from seattle.people import extract_contact_details


# (type, note) tuples — match what the scraper emits in
# seattle/people.py so the backfill and the live scrape stay aligned.
_FIELD_MAP = {
    "email":           ("email",   "Official email"),
    "phone":           ("voice",   "Office phone"),
    "fax":             ("fax",     "Office fax"),
    "office_address":  ("address", "Office"),
    "mailing_address": ("address", "Mailing"),
}


class Command(BaseCommand):
    help = "Backfill council member contact details (phone/fax/address) from seattle.gov."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Print planned changes without writing.")
        parser.add_argument("--person", type=str, default=None,
                            help="Limit to a single Person by name (exact match).")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        only = options["person"]

        qs = Person.objects.filter(links__note="City Council profile").distinct()
        if only:
            qs = qs.filter(name=only)

        total = qs.count()
        self.stdout.write(f"Backfilling contacts for {total} councilmembers (dry-run={dry}).")

        for person in qs:
            link = person.links.filter(note="City Council profile").first()
            if not link:
                continue
            # See `seattle/people.py` for the redirect rationale.
            try:
                resp = requests.get(link.url, timeout=10, allow_redirects=False)
            except requests.RequestException as e:
                self.stderr.write(f"  {person.name}: fetch failed — {e}")
                continue
            if resp.status_code != 200:
                self.stdout.write(
                    f"  {person.name}: skipped (HTTP {resp.status_code} — likely a "
                    f"former member whose URL redirects to their successor)"
                )
                continue

            contacts = extract_contact_details(resp.text)
            if not contacts:
                self.stderr.write(f"  {person.name}: no Contact Us block at {link.url}")
                continue

            self._apply(person, contacts, dry=dry)

        self.stdout.write(self.style.SUCCESS("Done."))

    def _apply(self, person, contacts: dict, dry: bool):
        actions: list[str] = []
        with transaction.atomic():
            for key, value in contacts.items():
                ocd_type, note = _FIELD_MAP[key]
                existing = person.contact_details.filter(type=ocd_type, note=note).first()
                if existing:
                    if existing.value == value:
                        continue
                    actions.append(f"update {ocd_type}/{note}: {existing.value!r} → {value!r}")
                    if not dry:
                        existing.value = value
                        existing.save(update_fields=["value"])
                else:
                    actions.append(f"add    {ocd_type}/{note}: {value!r}")
                    if not dry:
                        person.contact_details.create(type=ocd_type, value=value, note=note)

        prefix = f"  {person.name}:"
        if not actions:
            self.stdout.write(f"{prefix} already up to date")
        else:
            self.stdout.write(prefix)
            for a in actions:
                self.stdout.write(f"      {a}")

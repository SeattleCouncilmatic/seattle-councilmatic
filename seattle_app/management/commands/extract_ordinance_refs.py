"""Extract ordinance revision references from MunicipalCodeSection.full_text
into SectionOrdinanceRef rows.

Typical usage:
    python manage.py extract_ordinance_refs
    python manage.py extract_ordinance_refs --section-prefix 23.45
    python manage.py extract_ordinance_refs --dry-run

Parses the revision parenthetical at the end of each SMC section (e.g.
"(Ord. 126234, § 1, 2023; Ord. 124567, § 2, 2019)") into structured
(ordinance_number, section_reference, ordinance_year) rows.

Safe to re-run: refs for each section are replaced atomically so a
regex tweak propagates cleanly without leaving orphan rows.

The regex requires a 4-digit year on each match, which filters out
body references like "repeals Ord. 16003" that don't carry year
context. If we later encounter a legit revision entry with no year,
loosen the regex and re-run.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from seattle_app.services.ordinance_refs import extract_ordinance_refs


class Command(BaseCommand):
    help = "Extract ordinance revision references from section full_text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--section-prefix",
            help="Restrict to sections whose number starts with this prefix "
                 "(e.g. '23.45' for Chapter 23.45).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing to the database.",
        )

    def handle(self, *args, **opts):
        from seattle_app.models import MunicipalCodeSection, SectionOrdinanceRef

        qs = MunicipalCodeSection.objects.all()
        if opts["section_prefix"]:
            qs = qs.filter(section_number__startswith=opts["section_prefix"])

        counts = {
            "sections_scanned": 0,
            "sections_with_refs": 0,
            "refs_extracted": 0,
        }

        for section in qs.iterator(chunk_size=500):
            counts["sections_scanned"] += 1
            refs = extract_ordinance_refs(section.full_text or "")
            if not refs:
                continue
            counts["sections_with_refs"] += 1
            counts["refs_extracted"] += len(refs)

            if opts["dry_run"]:
                continue

            with transaction.atomic():
                SectionOrdinanceRef.objects.filter(section=section).delete()
                SectionOrdinanceRef.objects.bulk_create([
                    SectionOrdinanceRef(
                        section=section,
                        ordinance_number=r.ordinance_number,
                        section_reference=r.section_reference,
                        ordinance_year=r.ordinance_year,
                    )
                    for r in refs
                ])

        tag = " (DRY RUN)" if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"Done{tag}. "
            f"sections_scanned={counts['sections_scanned']} "
            f"sections_with_refs={counts['sections_with_refs']} "
            f"refs_extracted={counts['refs_extracted']}"
        ))

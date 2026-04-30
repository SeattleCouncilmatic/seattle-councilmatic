"""Download bill attachment files and extract their plain text into BillText.

Iterates the OCD/pupa Bill rows, finds the substantive attachments
(staff summary + signed canonical text), downloads them, and persists
the concatenated text + an audit trail to ``seattle_app.BillText``.
Idempotent: skips bills that already have a BillText row unless
``--force`` is set.

Why a backfill command instead of doing this inside the summarizer:
keeps the LLM pipeline decoupled from extraction quality. If we improve
the extractor later (table-aware, header-aware, OCR fallback) we can
re-run this command without re-running summaries; if we improve
prompts, we re-run summaries without re-downloading every bill's PDFs.

Usage:
    python manage.py extract_bill_text                # all bills missing BillText
    python manage.py extract_bill_text --limit 5      # smoke run
    python manage.py extract_bill_text --force        # re-extract even rows that exist
    python manage.py extract_bill_text --bill CB-120909  # single bill
"""
from __future__ import annotations

import logging
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from councilmatic_core.models import Bill

from seattle_app.models import BillText
from seattle_app.services.bill_text_extractor import combine_bill_documents

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Download bill attachments and cache their extracted text in BillText."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of bills to process (testing).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-extract even bills that already have BillText rows.",
        )
        parser.add_argument(
            "--bill",
            default=None,
            help="Bill identifier to process (e.g. 'CB 120909'). Skips all others.",
        )
        parser.add_argument(
            "--include-other",
            action="store_true",
            help=(
                "Also extract documents whose note doesn't match the staff-summary "
                "or signed-canonical patterns. Off by default to keep noise out."
            ),
        )

    def handle(self, *args, **opts):
        bills = self._target_bills(
            force=opts["force"],
            limit=opts["limit"],
            bill_identifier=opts["bill"],
        )

        total = len(bills)
        self.stdout.write(f"Extracting text for {total} bill(s)…")

        wrote = 0
        skipped_no_docs = 0
        skipped_no_match = 0
        for i, bill in enumerate(bills, start=1):
            self.stdout.write(self.style.NOTICE(
                f"[{i}/{total}] {bill.identifier} — {len(bill.documents.all())} doc(s)"
            ))
            documents = self._serialize_documents(bill)
            if not documents:
                self.stdout.write("  ! no documents on this bill, skipping")
                skipped_no_docs += 1
                continue

            text, extracted = combine_bill_documents(
                documents,
                include_other=opts["include_other"],
            )
            if not text:
                self.stdout.write(self.style.WARNING(
                    "  ! no usable text extracted (all documents are affidavits/other), skipping"
                ))
                skipped_no_match += 1
                # Still record the audit trail so re-runs don't silently skip again.
                self._save(bill, text="", extracted=extracted)
                continue

            self.stdout.write(self.style.SUCCESS(
                f"  → {len(text):,} chars from "
                f"{sum(1 for d in extracted if d.text)}/{len(extracted)} documents"
            ))
            self._save(bill, text=text, extracted=extracted)
            wrote += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Wrote {wrote} BillText row(s); "
            f"skipped {skipped_no_docs} (no docs), {skipped_no_match} (no match)."
        ))

    def _target_bills(
        self,
        *,
        force: bool,
        limit: Optional[int],
        bill_identifier: Optional[str],
    ) -> list[Bill]:
        qs = Bill.objects.all().order_by("-created_at")
        if bill_identifier:
            qs = qs.filter(identifier=bill_identifier)
        elif not force:
            # Skip bills whose extracted_text row already exists.
            qs = qs.filter(extracted_text__isnull=True)
        qs = qs.prefetch_related("documents__links")
        if limit is not None:
            qs = qs[:limit]
        return list(qs)

    @staticmethod
    def _serialize_documents(bill: Bill) -> list[dict]:
        """Flatten BillDocument + BillDocumentLink into the dict shape the
        extractor expects. Each (document, link) pair becomes one entry —
        a single document occasionally has multiple format variants."""
        out: list[dict] = []
        for doc in bill.documents.all():
            for link in doc.links.all():
                out.append({
                    "note": doc.note,
                    "url": link.url,
                    "media_type": link.media_type,
                })
        return out

    @staticmethod
    @transaction.atomic
    def _save(bill: Bill, *, text: str, extracted) -> None:
        audit = [
            {
                "note": d.note,
                "url": d.url,
                "media_type": d.media_type,
                "category": d.category,
                "char_count": len(d.text),
                "error": d.error,
            }
            for d in extracted
        ]
        BillText.objects.update_or_create(
            bill=bill,
            defaults={
                "text": text,
                "source_documents": audit,
            },
        )

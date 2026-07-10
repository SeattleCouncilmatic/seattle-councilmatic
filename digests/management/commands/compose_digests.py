"""Compose personalized digests: run the match queries, snapshot the
results into pending ``DigestSend`` rows, and submit the intro batch
(Phases 2-3, #235/#238).

For every active subscriber with the cadence enabled, matches the window's
council news against their preferences (see ``services/personalization``)
and creates a ``DigestSend(status=pending)`` carrying the
``matched_item_ids`` snapshot. Non-quiet rows then go into one Anthropic
Batch (one request per subscriber — a personalized intro paragraph), and
the batch id is stamped on ``compose_batch_id``. ``send_digest_batches``
polls the batch, persists the intros, renders, and delivers — the row is
the compose→send handoff, no state files.

The LLM step can only ever *add* to a digest: quiet-week rows skip it, a
missing API key or a submit failure leaves rows batch-less (they send
templated-only), and no exception from the intro machinery aborts the
compose. See ``services/llm_client.get_llm_client``.

Zero-match handling per the plan: weekly subscribers still get a short
"quiet week" digest (the cadence promise is a weekly email); daily
subscribers are skipped entirely (daily is "when there's news").

Usage:
    python manage.py compose_digests --cadence weekly
    python manage.py compose_digests --cadence daily --dry-run
    python manage.py compose_digests --cadence weekly --limit 3
"""
import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from digests.models import DigestSend, Subscriber
from digests.services import personalization
from digests.services.intro_prompt import build_intro_request, digest_model
from digests.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Match subscriber preferences against recent council activity, create pending DigestSend rows, and submit the intro batch."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cadence",
            required=True,
            choices=[DigestSend.CADENCE_WEEKLY, DigestSend.CADENCE_DAILY],
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report per-subscriber match counts without creating rows "
            "or calling the API.",
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
        # (DigestSend row, matched items) pairs that get an intro request —
        # items are still in memory here, so the batch request is built
        # without re-hydrating the snapshot.
        intro_work: list[tuple[DigestSend, list[dict]]] = []
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
                send = DigestSend.objects.create(
                    subscriber=subscriber,
                    cadence=cadence,
                    matched_item_ids=personalization.snapshot(items),
                    item_count=len(items),
                )
                if items:  # quiet-week digests need no LLM call
                    intro_work.append((send, items))
            composed += 1

        prefix = "[dry-run] Would compose" if opts["dry_run"] else "Composed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {composed} {cadence} digest(s); "
                f"{skipped_dedup} deduped, {skipped_quiet} skipped with no news."
            )
        )
        if not opts["dry_run"]:
            self._submit_intro_batch(intro_work, cadence)

    # ------------------------------------------------------------------ #

    def _submit_intro_batch(self, intro_work, cadence):
        """One Batch request per non-quiet digest. Every failure path
        leaves rows batch-less — send_digest_batches delivers those
        templated-only, so the intro can never block the weekly email."""
        if not intro_work:
            return
        client = get_llm_client()
        if client is None:
            self.stdout.write(
                "LLM backend off (or no API key); digests will send "
                "without intros."
            )
            return
        model = digest_model()
        requests = [
            build_intro_request(
                send.subscriber_id, send.subscriber.preferences,
                items, cadence, model,
            )
            for send, items in intro_work
        ]
        try:
            batch_id = client.submit_intro_batch(requests)
        except Exception:
            logger.exception("intro batch submit failed")
            self.stdout.write(self.style.WARNING(
                "Intro batch submit failed; digests will send without "
                "intros. See the log."
            ))
            return
        for send, _items in intro_work:
            send.compose_batch_id = batch_id
            send.save(update_fields=["compose_batch_id"])
        self.stdout.write(self.style.SUCCESS(
            f"Submitted intro batch {batch_id} "
            f"({len(requests)} request(s), model {model})."
        ))

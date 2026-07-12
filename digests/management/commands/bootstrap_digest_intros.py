"""Generate gold-standard digest intros with the bootstrap (Opus) model
(#239) — the same calibration pattern as ``bootstrap_section_summaries``:
run the expensive model once over representative inputs, curate the best
outputs into few-shot examples inside ``INTRO_SYSTEM_PROMPT``, and let the
cheap bulk model (Haiku) imitate them every week.

Builds synthetic preference profiles from whatever the DB actually holds
(current councilmembers, the busiest issue tags in the window, recently
actioned bills, districts) — no ``Subscriber`` rows are created; a shim
object stands in for ``SubscriberPreferences``. Each profile runs through
the SAME ``build_intro_request`` the weekly batch uses, so the exemplar
inputs match production shape exactly, then calls the Messages API
synchronously (a handful of one-offs — no batch round-trip).

Usage:
    python manage.py bootstrap_digest_intros --since 2026-05-01
    python manage.py bootstrap_digest_intros --since 2026-05-01 --dry-run
    python manage.py bootstrap_digest_intros --since 2026-05-01 --model claude-sonnet-5
"""
import json
from collections import Counter
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Q

from councilmatic_core.models import Bill
from opencivicdata.core.models import Membership, Person

from digests.services import personalization
from digests.services.intro_prompt import build_intro_request
from reps.models import District
from seattle_app.models import BillTags


class _Profile:
    """Duck-typed stand-in for SubscriberPreferences: exactly the four
    attributes match_items/_prefs_context read, backed by real querysets."""

    def __init__(self, label, *, issue_areas=None, rep_ids=None,
                 bill_ids=None, district=None):
        self.label = label
        self.issue_areas = issue_areas or []
        self.followed_reps = Person.objects.filter(id__in=rep_ids or [])
        self.followed_bills = Bill.objects.filter(id__in=bill_ids or [])
        self.district = district

    def describe(self):
        bits = []
        if self.issue_areas:
            bits.append("tags: " + ", ".join(self.issue_areas))
        names = list(self.followed_reps.values_list("name", flat=True))
        if names:
            bits.append("reps: " + ", ".join(names))
        idents = list(self.followed_bills.values_list("identifier", flat=True))
        if idents:
            bits.append("bills: " + ", ".join(idents))
        if self.district:
            bits.append(f"district: {self.district.number}")
        return "; ".join(bits) or "(empty)"


class Command(BaseCommand):
    help = "Generate gold-standard digest intros with the bootstrap model for prompt curation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            required=True,
            help="News-window start (YYYY-MM-DD) — pick one that gives the "
            "profiles real matched items (dev DBs are often stale).",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override settings.CLAUDE_BOOTSTRAP_MODEL for this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the profiles and their match counts; no API calls.",
        )

    def handle(self, *args, **opts):
        since = date.fromisoformat(opts["since"])
        model = opts["model"] or settings.CLAUDE_BOOTSTRAP_MODEL
        profiles = self._build_profiles(since)
        if not profiles:
            raise CommandError(
                "No profile matched anything in the window — widen --since."
            )

        client = None
        if not opts["dry_run"]:
            if not settings.ANTHROPIC_API_KEY:
                raise CommandError("ANTHROPIC_API_KEY not configured.")
            import anthropic

            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        for profile, items in profiles:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== {profile.label}: {profile.describe()} "
                f"[{len(items)} item(s)] ==="
            ))
            for item in items[:12]:
                self.stdout.write(
                    f"    - {item['identifier'] or item['title']}"
                    f" ({'; '.join(item['reasons'])})"
                )
            if opts["dry_run"]:
                continue
            request = build_intro_request(0, profile, items, "weekly", model)
            message = client.messages.create(**request["params"])
            text = next(
                (b.text for b in message.content if b.type == "text"), ""
            )
            data = json.loads(text)
            self.stdout.write(self.style.SUCCESS("  intro:"))
            for para in data.get("intro", "").split("\n\n"):
                self.stdout.write(f"  {para.strip()}\n")

    # ------------------------------------------------------------------ #

    def _build_profiles(self, since):
        """Assemble representative profiles from live data; drop the ones
        with no matches so every exemplar has real content."""
        today = date.today().isoformat()
        council_members = list(
            Membership.objects.filter(
                organization__name="Seattle City Council"
            )
            .filter(Q(end_date="") | Q(end_date__gte=today))
            .exclude(label="")
            .select_related("person")
        )
        rep_ids = list(dict.fromkeys(m.person_id for m in council_members))

        # Busiest issue tags among bills actioned in the window.
        active_bill_ids = list(
            Bill.objects.annotate(last_action=Max("actions__date"))
            .filter(last_action__gte=since.isoformat())
            .values_list("id", flat=True)
        )
        tag_counts = Counter(
            tag
            for tags in BillTags.objects.filter(
                bill_id__in=active_bill_ids
            ).values_list("tags", flat=True)
            for tag in tags
        )
        top_tags = [t for t, _n in tag_counts.most_common(4)]

        districts = {d.number: d for d in District.objects.all()}
        district_of_rep = {}
        for m in council_members:
            if m.label.startswith("District "):
                number = m.label.split(" ", 1)[1]
                if number in districts:
                    district_of_rep[m.person_id] = districts[number]

        candidates = []
        if top_tags:
            candidates.append(_Profile("issue-focused", issue_areas=top_tags[:2]))
        if len(rep_ids) >= 2:
            candidates.append(_Profile("rep-follower", rep_ids=rep_ids[:2]))
        if district_of_rep:
            candidates.append(_Profile(
                "district-only",
                district=next(iter(district_of_rep.values())),
            ))
        if len(active_bill_ids) >= 2:
            candidates.append(_Profile(
                "bill-watcher", bill_ids=active_bill_ids[:2]
            ))
        if top_tags and rep_ids:
            candidates.append(_Profile(
                "kitchen-sink",
                issue_areas=top_tags[2:4] or top_tags[:1],
                rep_ids=rep_ids[2:3] or rep_ids[:1],
                district=next(iter(district_of_rep.values()), None),
            ))
        if "At Large" in districts:
            candidates.append(_Profile(
                "at-large", district=districts["At Large"]
            ))

        profiles = []
        for profile in candidates:
            items = personalization.match_items(profile, since)
            if items:
                profiles.append((profile, items))
        return profiles

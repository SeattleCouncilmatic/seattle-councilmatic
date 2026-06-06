"""Per-councilmember stats aggregator for the rep-summary LLM prompt.

Builds a structured dict combining tenure, committee assignments,
sponsorship breakdown by issue-area tag, voting record, and the
RepBio prose. The dict is the *entire* input the LLM sees — bio
adds the qualitative texture, the stats add quantitative grounding,
and the structure is uniform so a single prompt handles all 11 reps.

Designed for re-aggregation cheapness: every counter / breakdown is
a single Django ORM aggregate, no per-bill Python loops. The full
``build_rep_stats_context`` for all 11 reps runs in well under a
second.

Used by ``seattle_app.management.commands.summarize_reps``. Not yet
wired to the frontend API — once the summary card lands, the
stats_snapshot stored on ``RepSummary`` is what's exposed, not this
function's live output (so the rendered card matches the prose that
was synthesized from it)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from datetime import date

from django.db.models import Count, Q

from councilmatic_core.models import Bill
from opencivicdata.core.models import Membership, Person
from opencivicdata.legislative.models import BillSponsorship, PersonVote

from seattle_app.models import BillTags


_COUNCIL_ORG_NAME = "Seattle City Council"
# Notable-sponsorships cap. Top-of-list bills the LLM should consider
# representative; small enough to keep the prompt under ~3 KB total,
# big enough to span topic clusters.
_NOTABLE_SPONSORSHIP_LIMIT = 8
# Top-N tag breakdown for sponsorship. 5 is enough to characterize a
# rep's portfolio without including statistical noise.
_TOP_TAG_LIMIT = 5


def build_rep_stats_context(person: Person) -> dict[str, Any]:
    """Top-level entry. Returns the dict passed verbatim into the
    rep-summary LLM prompt and persisted to ``RepSummary.stats_snapshot``.
    Order of keys is stable so JSON diffing across re-runs is meaningful."""
    return {
        "name": person.name,
        "tenure": _tenure_context(person),
        "committees": _committees_context(person),
        "bio": _bio_text(person),
        "sponsorship": _sponsorship_context(person),
        "voting": _voting_context(person),
    }


# ---------------------------------------------------------------- tenure
def _tenure_context(person: Person) -> dict[str, Any]:
    """Current Seattle City Council seat + start date (when available).

    Rep memberships in the DB sometimes appear as a single row with
    no start/end dates AND a separate populated row for the same
    seat (term boundaries from the OCD scraper). 'Active' means
    end_date is blank OR end_date is in the future; sort by populated
    start_date DESC so a row with a real start beats a placeholder."""
    today = date.today().isoformat()
    candidates = list(
        person.memberships
        .filter(organization__name=_COUNCIL_ORG_NAME)
        .filter(Q(end_date="") | Q(end_date__gte=today))
    )
    if not candidates:
        return {"seat": None, "start_date": None}
    # Prefer rows that actually have a start_date populated. Among
    # those, the most recent start wins (covers reps who returned
    # for a new term — most-recent membership is current). If no
    # row has a start_date, fall back to the first.
    candidates.sort(
        key=lambda m: (1 if m.start_date else 0, m.start_date or ""),
        reverse=True,
    )
    current = candidates[0]
    return {
        "seat": current.label or current.role or None,
        "start_date": current.start_date or None,
        "end_date": current.end_date or None,
    }


# ---------------------------------------------------------------- committees
_COMMITTEE_ROLE_ORDER = {"Chair": 0, "Vice-Chair": 1, "Member": 2}


def _committees_context(person: Person) -> list[dict[str, str]]:
    """Returns [{name, role}, ...] sorted Chair > Vice-Chair > Member,
    then by committee name. Mirrors ``reps.services._committees_for_person``
    but trimmed to just the fields the prompt needs (no org id, no
    source URL)."""
    qs = person.memberships.filter(
        organization__classification="committee"
    ).select_related("organization")
    rows = [
        {"name": m.organization.name, "role": m.role}
        for m in qs
    ]
    rows.sort(key=lambda r: (_COMMITTEE_ROLE_ORDER.get(r["role"], 99), r["name"]))
    return rows


# ---------------------------------------------------------------- bio
def _bio_text(person: Person) -> str | None:
    """RepBio prose if scraped; None otherwise (Solomon / Nelson lack a
    published seattle.gov About page — see WORK_LOG 2026-05-10)."""
    bio = getattr(person, "rep_bio", None)
    return bio.bio if bio else None


# ---------------------------------------------------------------- sponsorship
def _sponsorship_context(person: Person) -> dict[str, Any]:
    """Aggregate sponsorship breakdown. Distinguishes primary from
    cosponsor (the OCD ``primary`` boolean) so the prompt knows which
    bills the rep actually drove vs. signed on to. Issue-area counts
    come from the ``BillTags`` model (populated by the bill-tagger) —
    top 5 tags by primary-sponsorship count."""
    # Dedupe by bill_id — OCD's BillSponsorship can have multiple rows
    # per (person, bill) combo (different sponsorship classifications,
    # scrape-re-run residue). For "how many bills did this rep
    # sponsor," we want one count per bill.
    sponsorships = (
        BillSponsorship.objects
        .filter(person=person)
        .select_related("bill")
    )
    primary_bill_ids: set[str] = set()
    cosponsor_bill_ids: set[str] = set()
    for s in sponsorships:
        bid = s.bill_id
        if s.primary:
            primary_bill_ids.add(bid)
        else:
            cosponsor_bill_ids.add(bid)
    primary_count = len(primary_bill_ids)
    # Bills sponsored as cosponsor only — exclude bills also primary-
    # sponsored so we don't double-count a bill the rep led on.
    cosponsor_count = len(cosponsor_bill_ids - primary_bill_ids)

    # Issue-area tags live in the BillTags model (moved off OCD Bill.subject,
    # which the scrape importer clobbers to [] on every re-import — #217).
    # Fetch once for all primary bills; bills with no BillTags row contribute
    # nothing.
    tags_by_bill: dict[str, list[str]] = dict(
        BillTags.objects.filter(bill_id__in=primary_bill_ids)
        .values_list("bill_id", "tags")
    )
    # Tag breakdown is from primary sponsorships only. Cosponsoring signals
    # support but not portfolio focus — a rep who cosponsors a bill on someone
    # else's issue isn't claiming that issue area.
    tag_counter: Counter[str] = Counter()
    for bid in primary_bill_ids:
        for tag in tags_by_bill.get(bid, []):
            tag_counter[tag] += 1
    top_tags = [
        {"tag": tag, "count": n}
        for tag, n in tag_counter.most_common(_TOP_TAG_LIMIT)
    ]

    # Notable sponsorships: most recent primary-sponsored bills with
    # title. The LLM uses these for concrete grounding ("sponsored
    # ordinances on X, Y, Z") without us having to pre-pick themes.
    # OCD Bill rows lack created_at directly in some scraper paths;
    # join through councilmatic_core.Bill to surface the slug-side
    # ordering field that the rest of the codebase trusts.
    # `distinct()` because the BillSponsorship join can produce one
    # row per sponsorship record and a person may have multiple rows
    # for the same bill (e.g. amended sponsorships, or scrape re-runs
    # that didn't dedupe). Without distinct(), notable_sponsorships
    # repeats the same bill.
    notable_qs = (
        Bill.objects
        .filter(sponsorships__person=person, sponsorships__primary=True)
        .distinct()
        .order_by("-created_at")
        .values("id", "identifier", "title")[:_NOTABLE_SPONSORSHIP_LIMIT]
    )
    notable = [
        {
            "identifier": row["identifier"],
            "title": (row["title"] or "")[:200],
            "tags": tags_by_bill.get(row["id"], []),
        }
        for row in notable_qs
    ]

    return {
        "primary_count": primary_count,
        "cosponsor_count": cosponsor_count,
        "top_issue_areas": top_tags,
        "notable_sponsorships": notable,
    }


# ---------------------------------------------------------------- voting
def _voting_context(person: Person) -> dict[str, Any]:
    """Lifetime voting record aggregated by option. Returns counts
    plus a ``yes_pct`` derived from non-absent votes so the LLM can
    talk about voting record without us having to pre-bake phrasing.

    The percentage denominator excludes 'absent' and 'not voting' —
    those aren't votes against, they're non-participation, and
    folding them into the rate makes high-absence reps look
    artificially divergent. Abstentions stay in the denominator
    because they're an active voting choice."""
    breakdown_qs = (
        PersonVote.objects
        .filter(voter=person)
        .values("option")
        .annotate(n=Count("id"))
    )
    breakdown = {row["option"]: row["n"] for row in breakdown_qs}
    total = sum(breakdown.values())

    actively_voting = sum(
        n for opt, n in breakdown.items()
        if opt not in ("absent", "not voting")
    )
    yes = breakdown.get("yes", 0)
    yes_pct = round(100.0 * yes / actively_voting, 1) if actively_voting else None

    return {
        "total_votes_cast": total,
        "breakdown": breakdown,
        "yes_pct_of_active_votes": yes_pct,
    }

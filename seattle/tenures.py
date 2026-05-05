"""Hardcoded start dates for current Seattle City Council members.

The Legistar people endpoint doesn't expose tenure dates and the
seattle.gov per-member bio prose is unstructured (every office writes
it differently). Both the people scraper (`seattle/people.py`) and the
one-shot `backfill_tenure_dates` management command read this dict so
the data stays consistent across re-scrapes.

`start_date` semantics: **first day of current continuous service on
the council**, ISO-8601 (`YYYY-MM-DD`) or partial (`YYYY-MM` /
`YYYY`). For members elected to a brand-new seat at a regular
election, this is the inauguration date (typically January 2 in
Seattle). For appointed mid-term replacements, it's the day they were
sworn in to the appointment. For councilmembers returning to the
council after a break in service (e.g. Juarez 2016-2023 then
re-appointed 2025), this is the *current* tenure's start, not the
first-ever start; the rep header reads "Serving since…" which the
user expects to mean the current tenure.

When a councilmember's seat changes (new election, appointment, etc.):
update the entry here, run `python manage.py backfill_tenure_dates`
on prod, and the daily scrape will keep it in sync going forward.

Keys are `(person_name, membership_label)` matching what the people
scraper passes to `Person.add_membership(label=...)` — pairing both
guards against name collisions across former and current holders of
the same seat.
"""

# (name, district/position label) → start_date (ISO 8601, partial OK)
COUNCIL_TENURE_START = {
    # 2023-cohort district seats — sworn in Jan 2, 2024.
    ("Rob Saka",          "District 1"): "2024-01-02",
    ("Joy Hollingsworth", "District 3"): "2024-01-02",
    ("Maritza Rivera",    "District 4"): "2024-01-02",
    ("Robert Kettle",     "District 7"): "2024-01-02",
    # Strauss was first elected to D6 in Nov 2019 (took office Jan 6,
    # 2020); re-elected 2023. "Serving since" = first day of current
    # continuous service.
    ("Dan Strauss",       "District 6"): "2020-01-06",

    # Mid-term replacements — exact dates need verification before
    # the backfill runs on prod. Set to None to skip the row entirely
    # rather than ship a wrong date. Update + re-run backfill once
    # confirmed.
    ("Eddie Lin",             "District 2"): None,  # TODO: verify date Lin was sworn in (replaced Tammy Morales)
    ("Debora Juarez",         "District 5"): None,  # TODO: verify Juarez's current-tenure start (replaced Cathy Moore)
    ("Alexis Mercedes Rinck", "Position 8"): None,  # TODO: verify (Nov 2024 special election win)
    ("Dionne Foster",         "Position 9"): None,  # TODO: verify (replaced Sara Nelson)
}


def lookup_start_date(name: str, label: str) -> str | None:
    """Return the start date for (name, label), or None if we don't
    have a verified date yet. Callers should treat None as "skip" —
    the field stays unset on the Membership row, which is preferable
    to a guessed date showing up on the live site."""
    return COUNCIL_TENURE_START.get((name, label))

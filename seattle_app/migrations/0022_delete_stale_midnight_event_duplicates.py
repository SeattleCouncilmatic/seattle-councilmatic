"""Delete pre-2026-04-28 stale midnight Event rows.

Before PR #34 (committed 2026-04-28) the events scraper read only
Legistar's `EventDate` field, which always carries midnight; the wall-
clock time lives in a separate `EventTime` field. Every event scraped
before that fix landed at midnight Pacific (07:00 UTC during PDT,
08:00 UTC during PST). When the fix shipped, the next scrape created
*new* event rows at the correct time — pupa upserts on (name +
start_date), so a different start_date produces a new row rather than
updating the existing one. Result: 91 (name, date) groups in the DB
with both a stale midnight row and a corrected row, double-displaying
in `/events/`.

Criterion (verified safe — runs against the production DB return:
91 candidates, 0 unsafe groups):
- group all Event rows by (name, date-prefix-of-start_date)
- a row is a deletion candidate if its time component is exactly
  `T07:00:00+00:00` or `T08:00:00+00:00` (midnight Pacific in PDT/PST)
  *and* the (name, date) group contains at least one non-midnight
  sibling. The sibling guarantees we know the real meeting time and
  preserves it; we never delete the only row for a given (name, date).

Uses Django ORM `.delete()` so OCD's model-level `on_delete=CASCADE`
fires for the related EventAgendaItem / EventDocument / EventLink /
EventMedia / EventParticipant / EventSource rows, plus the downstream
`councilmatic_core.Event` row that also has CASCADE on its OCD FK
(checked: the DB-level FK constraints are `NO ACTION`, but Django
model code is `CASCADE`, so ORM delete is the only safe path —
raw-SQL DELETE on `opencivicdata_event` would error on the FK).

Reverse is a no-op: the deleted rows were buggy data; restoring them
would re-create the duplicate display.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import migrations


_MIDNIGHT_SUFFIXES = ("T07:00:00+00:00", "T08:00:00+00:00")


def delete_midnight_duplicates(apps, schema_editor):
    Event = apps.get_model("legislative", "Event")

    buckets: dict[tuple[str, str], list] = defaultdict(list)
    for event in Event.objects.all():
        buckets[(event.name, event.start_date[:10])].append(event)

    to_delete_ids: list[str] = []
    for evs in buckets.values():
        if len(evs) < 2:
            continue
        midnight = [e for e in evs if e.start_date[10:] in _MIDNIGHT_SUFFIXES]
        non_midnight = [e for e in evs if e not in midnight]
        if midnight and non_midnight:
            to_delete_ids.extend(e.id for e in midnight)

    if to_delete_ids:
        Event.objects.filter(id__in=to_delete_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("seattle_app", "0021_update_council_profile_urls"),
        # Make sure the OCD legislative app's tables are in their final
        # shape before we touch them.
        ("legislative", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            delete_midnight_duplicates,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

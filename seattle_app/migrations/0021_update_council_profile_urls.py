"""Update existing City Council profile links from the old anchor pattern
(`/council/members#DeboraJuarez`) to the per-member detail page pattern
(`/council/members/debora-juarez`).

The detail pages carry richer content (about, committees, staff, blog
posts) and are the surface we want to link to going forward. The slug
rule mirrors `seattle.people.profile_slug`: lowercase + spaces→hyphens,
with `Robert Kettle → bob-kettle` since seattle.gov uses his preferred
name on the URL.

Reverse is a no-op — there's no value in restoring the old anchor URLs.
"""

from __future__ import annotations

from django.db import migrations


_BASE = "https://www.seattle.gov/council/members"
_OVERRIDES = {
    "Robert Kettle": "bob-kettle",
}


def _slug(name: str) -> str:
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    return name.strip().lower().replace(" ", "-")


def update_profile_urls(apps, schema_editor):
    PersonLink = apps.get_model("core", "PersonLink")
    for link in PersonLink.objects.filter(note="City Council profile"):
        new_url = f"{_BASE}/{_slug(link.person.name)}"
        if link.url != new_url:
            link.url = new_url
            link.save(update_fields=["url"])


class Migration(migrations.Migration):
    dependencies = [
        ("seattle_app", "0020_repopulate_affected_sections"),
    ]

    operations = [
        migrations.RunPython(
            update_profile_urls,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

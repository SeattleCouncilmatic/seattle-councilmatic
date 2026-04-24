"""Seed ZoningCode with legacy/overlay codes that SDCI's zoning-polygon
layer uses but the current SMC legend page (KEY TO DISTRICT DESIGNATIONS)
doesn't include.

Three groups:
  - SF 5000 / SF 7200 / SF 9600: legacy Single-Family codes. Renamed to
    NR3 / NR2 / NR1 by Seattle's 2023 Neighborhood Residential zoning
    rewrite. SDCI still publishes the legacy codes on its polygon layer.
  - MIO: Major Institutions Overlay, defined in SMC Ch. 23.69 (not on
    the alphabetical legend page because it's an overlay, not a base zone).
  - SMR: Seattle Mixed Residential, a SLU-area variant.

These rows get `source_pdf_page=NULL` because they're not in the PDF
legend. Subsequent `extract_zoning_legend` runs leave them alone since
upsert is keyed on `abbreviation` and doesn't purge non-PDF rows.
"""

from django.db import migrations


LEGACY_CODES = [
    (
        "SF 5000",
        "Single-Family Residential, 5,000 sq ft minimum lot "
        "(legacy; renamed Neighborhood Residential 3 in 2023)",
    ),
    (
        "SF 7200",
        "Single-Family Residential, 7,200 sq ft minimum lot "
        "(legacy; renamed Neighborhood Residential 2 in 2023)",
    ),
    (
        "SF 9600",
        "Single-Family Residential, 9,600 sq ft minimum lot "
        "(legacy; renamed Neighborhood Residential 1 in 2023)",
    ),
    ("MIO", "Major Institutions Overlay (SMC Ch. 23.69)"),
    ("SMR", "Seattle Mixed Residential"),
]


def add_legacy_codes(apps, schema_editor):
    ZoningCode = apps.get_model("seattle_app", "ZoningCode")
    for abbrev, name in LEGACY_CODES:
        ZoningCode.objects.update_or_create(
            abbreviation=abbrev,
            defaults={"name": name},
        )


def remove_legacy_codes(apps, schema_editor):
    ZoningCode = apps.get_model("seattle_app", "ZoningCode")
    ZoningCode.objects.filter(
        abbreviation__in=[code for code, _ in LEGACY_CODES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("seattle_app", "0007_drop_councildistrict_use_reps"),
    ]
    operations = [
        migrations.RunPython(add_legacy_codes, remove_legacy_codes),
    ]

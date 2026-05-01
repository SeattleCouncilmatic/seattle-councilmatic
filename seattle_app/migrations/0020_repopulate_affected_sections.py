"""Re-resolve LegislationSummary.affected_sections M2M to handle
multi-cite values.

The original `_upsert_summary` (in `summarize_legislation.py`) treated
each `key_changes[].affected_section` as one literal section number,
so a value like `"1.04.020, 1.04.070"` failed the
`section_number__in=[...]` lookup and contributed nothing to the M2M.
The forward-fix in that command now extracts every 2- or 3-part SMC
cite via regex; this migration applies the same extraction to all
existing LegislationSummary rows so their affected_sections M2M is
correct without re-running the LLM pipeline.

Reverse is a no-op — the original (buggy) M2M state isn't worth
preserving.
"""

from __future__ import annotations

import re

from django.db import migrations


_SMC_CITE_RE = re.compile(r"\d+[A-Z]?\.\d+[A-Z]?(?:\.\d+[A-Z]?)?")


def repopulate_affected_sections(apps, schema_editor):
    LegislationSummary = apps.get_model("seattle_app", "LegislationSummary")
    MunicipalCodeSection = apps.get_model("seattle_app", "MunicipalCodeSection")

    for summary in LegislationSummary.objects.all():
        cites: set[str] = set()
        for kc in (summary.key_changes or []):
            cites.update(_SMC_CITE_RE.findall(kc.get("affected_section") or ""))
        if cites:
            sections = MunicipalCodeSection.objects.filter(section_number__in=cites)
            summary.affected_sections.set(sections)
        else:
            summary.affected_sections.clear()


class Migration(migrations.Migration):
    dependencies = [
        ("seattle_app", "0019_legislationsummary_summary_batch_id"),
    ]

    operations = [
        migrations.RunPython(
            repopulate_affected_sections,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

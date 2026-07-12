# Upstream django-councilmatic dropped `headshot` from its Person model, but
# our schema is pinned at councilmatic_core.0053 (see digests/0001), so the
# column survives as NOT NULL with no default — and the library's post_save
# signal, which mirrors every new OCD Person into councilmatic_core_person
# through the ORM, can't populate a column its model no longer has. Any code
# path that creates a Person (tests were the first to hit it) violates the
# constraint. Give the orphaned column a DB-level default, guarded so this
# no-ops if a future upstream migration removes the column for real.
#
# This lives in digests (not a councilmatic_core migration) deliberately:
# generating one there recreates the phantom-0054 hazard (#187).
from django.db import migrations

_FORWARD = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilmatic_core_person'
      AND column_name = 'headshot'
  ) THEN
    ALTER TABLE councilmatic_core_person
      ALTER COLUMN headshot SET DEFAULT '';
  END IF;
END $$;
"""

_REVERSE = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilmatic_core_person'
      AND column_name = 'headshot'
  ) THEN
    ALTER TABLE councilmatic_core_person
      ALTER COLUMN headshot DROP DEFAULT;
  END IF;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("digests", "0003_digestsend_created_at_digestsend_error_and_more"),
        # The table must exist; 0053 is the pinned tip (digests/0001).
        ("councilmatic_core", "0053_add_councilmatic_bio"),
    ]

    operations = [
        migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE),
    ]

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import migrations


# tsvector body: weighted A/B/C across section_number, title, full_text.
# Stored as a generated column so PG keeps it in sync with no trigger or
# Django save() override — works for ORM, bulk_create, raw SQL, fixtures.
SEARCH_VECTOR_EXPR = """
    setweight(to_tsvector('english', coalesce(section_number, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(full_text, '')), 'C')
"""


class Migration(migrations.Migration):

    dependencies = [
        ('seattle_app', '0013_titleappendix'),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"""
                ALTER TABLE seattle_app_municipalcodesection
                ADD COLUMN search_vector tsvector
                GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPR}) STORED;
            """,
            reverse_sql=
                "ALTER TABLE seattle_app_municipalcodesection "
                "DROP COLUMN search_vector;",
            state_operations=[
                migrations.AddField(
                    model_name='municipalcodesection',
                    name='search_vector',
                    field=SearchVectorField(editable=False, null=True),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name='municipalcodesection',
            index=GinIndex(
                fields=['search_vector'],
                name='smc_section_search_idx',
            ),
        ),
    ]

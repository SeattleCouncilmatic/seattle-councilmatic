from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


# pg_trgm + a trigram GIN index on section_number lets the search
# endpoint do fast prefix / fuzzy matching on legal citations (e.g. a
# user typing "23.47A" should surface 23.47A.004, 23.47A.010, etc.).
# tsvector handles word search but tokenizes "23.47A.004" as a single
# atomic token, so partial-citation queries can't reach it via FTS.
class Migration(migrations.Migration):

    dependencies = [
        ('seattle_app', '0014_municipalcodesection_search_vector'),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name='municipalcodesection',
            index=GinIndex(
                fields=['section_number'],
                name='smc_section_number_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
    ]

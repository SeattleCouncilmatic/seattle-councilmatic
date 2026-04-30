import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('councilmatic_core', '0001_initial'),
        ('seattle_app', '0017_municipalcodesection_summary_batch_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='BillText',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                )),
                ('text', models.TextField(
                    blank=True,
                    help_text=(
                        'Concatenated plain text of all chosen attachments, with '
                        'section markers between sources (staff summary first, then '
                        'signed canonical text).'
                    ),
                )),
                ('source_documents', models.JSONField(
                    blank=True,
                    default=list,
                    help_text=(
                        'Per-document audit trail: list of '
                        '{note, url, media_type, category, char_count, error}.'
                    ),
                )),
                ('extracted_at', models.DateTimeField(auto_now_add=True)),
                ('last_regenerated', models.DateTimeField(auto_now=True)),
                ('bill', models.OneToOneField(
                    help_text='The legislation whose attachments produced this text.',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='extracted_text',
                    to='councilmatic_core.bill',
                )),
            ],
            options={
                'verbose_name': 'Bill Text',
                'verbose_name_plural': 'Bill Texts',
            },
        ),
    ]

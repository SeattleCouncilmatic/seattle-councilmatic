from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seattle_app', '0016_codetitle_codechapter'),
    ]

    operations = [
        migrations.AddField(
            model_name='municipalcodesection',
            name='summary_batch_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    "Anthropic Message Batches ID this summary came from "
                    "(e.g., 'msgbatch_01PCxUY7AHperTdVueAxmYr7'). Empty for "
                    "synchronous one-off generations or legacy rows."
                ),
                max_length=64,
            ),
        ),
    ]

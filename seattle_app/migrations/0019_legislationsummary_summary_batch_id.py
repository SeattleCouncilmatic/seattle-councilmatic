from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seattle_app', '0018_billtext'),
    ]

    operations = [
        migrations.AddField(
            model_name='legislationsummary',
            name='summary_batch_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    "Anthropic Message Batches ID this summary came from "
                    "(e.g., 'msgbatch_01PCxUY7AHperTdVueAxmYr7'). Empty for "
                    "synchronous one-off generations."
                ),
                max_length=64,
            ),
        ),
    ]

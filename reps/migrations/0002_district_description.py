from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reps', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='district',
            name='description',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Short description of the neighborhoods/area this district covers',
                max_length=255,
            ),
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_auto_20241111_1450'),
        ('reps', '0002_district_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='RepBio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bio', models.TextField(help_text="Biographical prose, paragraphs joined with '\\n\\n'.")),
                ('source_url', models.URLField(help_text='seattle.gov URL the bio was scraped from.', max_length=500)),
                ('scraped_at', models.DateTimeField(auto_now=True, help_text='Last time the bio was (re-)scraped.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('person', models.OneToOneField(help_text='OCD Person this bio belongs to.', on_delete=django.db.models.deletion.CASCADE, related_name='rep_bio', to='core.person')),
            ],
            options={
                'verbose_name': 'Rep biographical text',
                'verbose_name_plural': 'Rep biographical texts',
            },
        ),
    ]

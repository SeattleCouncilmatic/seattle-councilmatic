# Hand-written (Docker dev env unavailable on this machine, GDAL not on
# host PATH). Verify with `manage.py migrate --check seattle_app` inside
# the dev container before merging.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seattle_app', '0024_eventsummary'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatUsageLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation_id', models.CharField(blank=True, help_text='Client-generated UUID for the conversation this turn belongs to. Used to apply the per-conversation turn cap. Not linked to any user identity.', max_length=64)),
                ('ip_hash', models.CharField(blank=True, help_text='SHA-256 of (client IP + server salt). Empty if request had no resolvable IP.', max_length=64)),
                ('model_used', models.CharField(help_text="The Claude model that produced this turn (e.g., 'claude-haiku-4-5-20251001').", max_length=64)),
                ('input_tokens', models.IntegerField(default=0, help_text='Uncached input tokens charged for this turn (excludes cache reads).')),
                ('cached_input_tokens', models.IntegerField(default=0, help_text='Tokens read from prompt cache (charged at ~10% of input rate).')),
                ('output_tokens', models.IntegerField(default=0, help_text='Tokens produced by the model for this turn.')),
                ('tool_call_count', models.IntegerField(default=0, help_text='How many tool invocations the model made before producing the final answer.')),
                ('estimated_cost_usd', models.DecimalField(decimal_places=6, default=0, help_text="Estimated USD cost for this turn using list prices for model_used. Advisory — Anthropic's actual invoice is authoritative.", max_digits=8)),
            ],
            options={
                'verbose_name': 'Chat Usage Log',
                'verbose_name_plural': 'Chat Usage Logs',
                'indexes': [
                    models.Index(fields=['created_at'], name='chatusage_created_idx'),
                    models.Index(fields=['conversation_id'], name='chatusage_conv_idx'),
                ],
            },
        ),
    ]

"""Subscriber storage for personalized email digests (#231).

Privacy constraints that shape these models:

- ``Subscriber.email`` is the only PII we hold. It is never logged (an
  email-redaction filter guards the console handler — see
  ``seattle_app.logging_filters.EmailRedactionFilter``), never sent to
  Anthropic, and code paths reference ``subscriber.id`` instead.
- Manage/unsubscribe links use *stateless* HMAC tokens derived from
  ``(purpose, id, unsubscribe_token_version)`` — see
  ``digests/services/tokens.py``. Bumping the version revokes every
  outstanding link for that subscriber without storing tokens.
- Unsubscribed rows are hard-deleted after a retention window by
  ``manage.py purge_unsubscribed`` (right-to-delete; keeps the standing
  pool of stored addresses small).
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_issue_areas(value):
    """Preference tags must come from the controlled 20-tag vocabulary the
    bill-tagging pipeline writes to ``BillTags`` — otherwise the digest
    match query could never find anything for them."""
    # Lazy import: claude_service pulls in the anthropic SDK, which models
    # shouldn't load (or need) at app-registry time.
    from seattle_app.services.claude_service import BILL_TAG_VOCABULARY

    if not isinstance(value, list):
        raise ValidationError("issue_areas must be a list of tags.")
    unknown = [t for t in value if t not in BILL_TAG_VOCABULARY]
    if unknown:
        raise ValidationError(f"Unknown issue areas: {unknown}")


class Subscriber(models.Model):
    STATUS_PENDING = "pending"          # signed up, hasn't clicked the verify link
    STATUS_ACTIVE = "active"            # double opt-in complete; receives digests
    STATUS_UNSUBSCRIBED = "unsubscribed"
    STATUS_BOUNCED = "bounced"          # hard bounce; never send again
    STATUS_COMPLAINED = "complained"    # spam complaint; never send again
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending verification"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_UNSUBSCRIBED, "Unsubscribed"),
        (STATUS_BOUNCED, "Bounced"),
        (STATUS_COMPLAINED, "Complained"),
    ]

    email = models.EmailField(
        max_length=254,
        unique=True,
        help_text="Stored lowercased so uniqueness is case-insensitive. "
        "Never log this value — use subscriber.id in code paths.",
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    verification_token = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        default=None,
        help_text="One-shot double-opt-in token (secrets.token_urlsafe). "
        "Cleared on verification; NULL rows don't collide on the unique index.",
    )
    unsubscribe_token_version = models.PositiveIntegerField(
        default=1,
        help_text="HMAC'd into manage/unsubscribe tokens. Bump to revoke all "
        "outstanding links for this subscriber.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Start of the purge_unsubscribed retention clock.",
    )
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_bounce_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Digest subscriber"

    def __str__(self):
        # id, not email — this string shows up in logs and admin titles.
        return f"Subscriber {self.pk} ({self.status})"

    def save(self, *args, **kwargs):
        # Normalize at the model layer so every write path — views, shell,
        # tests — hits the same case-insensitive uniqueness.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def mark_unsubscribed(self):
        self.status = self.STATUS_UNSUBSCRIBED
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=["status", "unsubscribed_at"])


class SubscriberPreferences(models.Model):
    """What this subscriber wants in their digest. The four personalization
    dimensions are UNIONed by the match query (Phase 2): any one match puts
    an item in the digest."""

    subscriber = models.OneToOneField(
        Subscriber,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    weekly_enabled = models.BooleanField(default=True)
    daily_enabled = models.BooleanField(
        default=False,
        help_text="Daily-when-there's-news cadence. Accepted and stored from "
        "day one; the daily cron stays off until after launch.",
    )
    issue_areas = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_issue_areas],
        help_text="Subset of the BILL_TAG_VOCABULARY issue-area tags.",
    )
    followed_reps = models.ManyToManyField(
        "core.Person",
        blank=True,
        related_name="digest_followers",
        help_text="OCD Person rows for followed councilmembers.",
    )
    followed_bills = models.ManyToManyField(
        # councilmatic_core.Bill shares its pk with the OCD Bill (MTI), so
        # this joins cleanly to sponsorships/actions AND carries the slug
        # needed for links in rendered emails.
        "councilmatic_core.Bill",
        blank=True,
        related_name="digest_followers",
        help_text="Individual bills the subscriber follows.",
    )
    district = models.ForeignKey(
        "reps.District",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="digest_subscribers",
    )

    class Meta:
        verbose_name = "Subscriber preferences"
        verbose_name_plural = "Subscriber preferences"

    def __str__(self):
        return f"Preferences for subscriber {self.subscriber_id}"


class DigestSend(models.Model):
    """One digest email, from composition through delivery. ``compose_digests``
    creates the row in ``pending`` with the ``matched_item_ids`` snapshot;
    ``send_digest_batches`` renders from the snapshot and flips it to ``sent``
    (or ``failed``). The row IS the compose state — the plan's JSON state
    files predate the #208 state-lives-in-the-DB refactor. Also used for
    dedup (one send per cadence per day), audit, cost attribution, and as
    the snapshot the future feed page re-renders."""

    CADENCE_WEEKLY = "weekly"
    CADENCE_DAILY = "daily"
    CADENCE_CHOICES = [(CADENCE_WEEKLY, "Weekly"), (CADENCE_DAILY, "Daily")]

    STATUS_PENDING = "pending"  # composed, snapshot taken, not yet rendered/sent
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    subscriber = models.ForeignKey(
        # CASCADE: right-to-delete hard-deletes the subscriber row, and the
        # send log must not orphan references to deleted PII owners.
        Subscriber,
        on_delete=models.CASCADE,
        related_name="sends",
    )
    cadence = models.CharField(max_length=8, choices=CADENCE_CHOICES)
    status = models.CharField(
        max_length=8,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When compose_digests created the row (composition time).",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Delivery time. NULL until send_digest_batches sends it.",
    )
    error = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Why a failed send failed. Email-redacted BEFORE storing — "
        "SMTP exceptions embed the recipient address and this field renders "
        "in the admin.",
    )
    item_count = models.PositiveIntegerField(default=0)
    postmark_message_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Provider message id. Empty under the SMTP transport.",
    )
    compose_batch_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Anthropic Batch this send's LLM content came from. Empty "
        "for non-LLM sends (Phase 2 templated digests).",
    )
    bounce_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Set by the Postmark webhook (Phase 4).",
    )
    matched_item_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot of [{type, id, reasons}, ...] items in this "
        "digest — not a live query. Reasons are the compose-time match "
        "explanations; content (titles, summaries) is re-fetched by id at "
        "render time. Read by the future feed page.",
    )
    llm_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Parsed LLM output for this send ({intro} in v1). Stored "
        "so re-render/debug never needs a second LLM call.",
    )

    class Meta:
        verbose_name = "Digest send"
        indexes = [
            # Dedup lookup: "has this subscriber already gotten a <cadence>
            # digest today?"
            models.Index(fields=["subscriber", "cadence", "sent_at"]),
        ]

    def __str__(self):
        return f"{self.cadence} send to subscriber {self.subscriber_id} at {self.sent_at:%Y-%m-%d}"


class DigestConfig(models.Model):
    """Singleton (pk=1) runtime configuration, toggled in the Django admin —
    the same pattern as ``PipelineAlertState``. The admin checkbox is the
    ONLY control; there is deliberately no env-var override (split-brain
    config drift is what the WORK_LOG model-defaults convention exists to
    prevent). Future runtime flags (e.g. Phase 5's DIGEST_INCLUDE_BLURBS)
    belong on this row too.

    ``signups_enabled`` gates ACQUISITION only — the subscribe endpoint and
    the SPA's subscribe form. Confirm/manage/preferences/unsubscribe stay
    live regardless, so unticking it post-launch (kill switch) never breaks
    unsubscribe links already sitting in inboxes.
    """

    signups_enabled = models.BooleanField(
        help_text="Allow new digest signups. Off = subscribe endpoint 403s "
        "and the SPA hides the form; existing subscribers are unaffected.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Digest configuration"
        verbose_name_plural = "Digest configuration"

    def __str__(self):
        return f"Digest configuration (signups {'open' if self.signups_enabled else 'closed'})"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce the singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        # Seeded on first access: open in dev (DEBUG), closed in prod — so
        # merged digest code rides along on prod deploys with signups shut
        # until launch day ticks the box.
        obj, _ = cls.objects.get_or_create(
            pk=1, defaults={"signups_enabled": settings.DEBUG}
        )
        return obj

    @classmethod
    def signups_open(cls) -> bool:
        return cls.load().signups_enabled

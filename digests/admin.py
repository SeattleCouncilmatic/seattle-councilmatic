"""Intentionally limited admin for subscriber data (#231).

Raw email addresses never render in the admin — every list/detail surface
shows a masked form (``j***@e***.org``). Rows are read-only except delete,
which stays enabled as the manual right-to-delete escape hatch. There is
deliberately no search-by-email and no add/change: subscriptions only enter
through the double-opt-in flow, and support lookups go through ``manage.py
shell`` where access is already shell-level.
"""
from django.contrib import admin

from .models import DigestConfig, DigestSend, Subscriber, SubscriberPreferences


def _mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
        dom_head, _, dom_tail = domain.partition(".")
        return f"{local[:1]}***@{dom_head[:1]}***.{dom_tail}"
    except (ValueError, AttributeError):
        return "***"


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("id", "masked_email", "status", "created_at", "verified_at", "last_sent_at")
    list_filter = ("status",)
    ordering = ("-created_at",)
    # Every concrete field is excluded from the change form; the masked
    # readouts below are the only visibility.
    exclude = ("email", "verification_token")
    readonly_fields = (
        "masked_email",
        "status",
        "unsubscribe_token_version",
        "created_at",
        "verified_at",
        "unsubscribed_at",
        "last_sent_at",
        "last_bounce_at",
    )

    @admin.display(description="Email (masked)")
    def masked_email(self, obj):
        return _mask_email(obj.email)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SubscriberPreferences)
class SubscriberPreferencesAdmin(admin.ModelAdmin):
    list_display = ("subscriber_id", "weekly_enabled", "daily_enabled", "district")
    readonly_fields = (
        "subscriber",
        "weekly_enabled",
        "daily_enabled",
        "issue_areas",
        "followed_reps",
        "followed_bills",
        "district",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DigestConfig)
class DigestConfigAdmin(admin.ModelAdmin):
    """The one EDITABLE thing in this admin (everything else is read-only
    subscriber data): the signups launch gate / kill switch."""

    list_display = ("__str__", "signups_enabled", "updated_at")
    readonly_fields = ("updated_at",)

    def get_queryset(self, request):
        # Ensure the singleton exists so the toggle is always visible in
        # the changelist — without this, a fresh deploy shows an empty
        # list with no Add button and nothing to click.
        DigestConfig.load()
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False  # the singleton auto-creates; pk=1 is enforced in save()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DigestSend)
class DigestSendAdmin(admin.ModelAdmin):
    list_display = ("id", "subscriber_id", "cadence", "sent_at", "item_count", "bounce_status")
    list_filter = ("cadence", "bounce_status")
    ordering = ("-sent_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

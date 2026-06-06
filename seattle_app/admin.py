"""Django admin registrations for the underlying OCD models that this
project uses as editorial data — the bits a non-coder maintainer
should be able to edit without a deploy. Currently:

- `Membership.start_date` / `end_date` (tenure dates surfaced as
  "Serving since…" on `RepDetail`). Legistar doesn't expose these and
  seattle.gov bio prose is too varied to parse, so the right place
  for this data is a curated DB field editable here.

OCD itself doesn't ship admin registrations, so we add them in
this project. Most fields are read-only because the scraper owns
them — only the editorial bits (tenure dates, primarily) are
writable from admin.
"""

from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.utils.html import format_html
from opencivicdata.core.models import Person, Membership, Organization

from seattle_app.models import BatchRun, BillTags, PipelineRun, PipelineStep


# Pre-existing admin registrations on these OCD models (something
# upstream registers `Person` as `core.PersonAdmin`). Unregister first
# so our richer ones — with the Membership inline and the editable
# tenure dates — take precedence. Wrapped in NotRegistered guards
# because the unregister path differs by environment / install order.
for _m in (Person, Membership, Organization):
    try:
        admin.site.unregister(_m)
    except NotRegistered:
        pass


class MembershipInline(admin.TabularInline):
    model = Membership
    fk_name = "person"
    extra = 0
    fields = ("organization", "label", "role", "start_date", "end_date")
    readonly_fields = ("organization", "label", "role")
    can_delete = False
    show_change_link = True


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    """Browse councilmembers, with an inline showing their memberships
    so you can edit tenure dates without bouncing to the Membership
    admin. The Person record itself is scraper-managed and not
    editable here — only the inline's `start_date` / `end_date`."""
    list_display = ("name",)
    search_fields = ("name",)
    fields = ("name",)
    readonly_fields = ("name",)
    inlines = [MembershipInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    """Direct list view of all memberships — useful for finding e.g.
    every "District N" membership at a glance and editing tenure
    dates. Form is intentionally minimal: only `start_date` and
    `end_date` are editable; the rest of the row metadata is
    scraper-managed and read-only context (rendered in the title /
    breadcrumb, not as form fields, to avoid any cross-field
    validation surprises with FKs that have `null=True, blank=False`
    on the upstream OCD model)."""
    list_display = ("person_name", "organization_name", "label",
                    "role", "start_date", "end_date")
    list_filter = ("organization", "role")
    search_fields = ("person__name", "label")
    fields = ("start_date", "end_date")

    def has_add_permission(self, request):
        # Memberships come from the scraper; admin is for editing
        # tenure dates on existing rows, not creating new ones.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Person", ordering="person__name")
    def person_name(self, obj):
        return obj.person.name if obj.person else (obj.person_name or "")

    @admin.display(description="Organization", ordering="organization__name")
    def organization_name(self, obj):
        return obj.organization.name if obj.organization else ""


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Read-only browse — useful for confirming committee names when
    filtering memberships in the Membership admin above. Nothing is
    editable here; org metadata is fully scraper-managed."""
    list_display = ("name", "classification")
    list_filter = ("classification",)
    search_fields = ("name",)
    fields = ("name", "classification")
    readonly_fields = ("name", "classification")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --------------------------------------------------------------------------- #
#  Pipeline observability (issue #209) — staff-only health view of the LLM     #
#  Batch pipeline's PipelineRun / BatchRun rows. Machine-written, so these are #
#  view-only (no add/change); delete stays enabled for pruning old rows.       #
# --------------------------------------------------------------------------- #

_BATCH_STATUS_COLORS = {
    BatchRun.STATUS_SUBMITTED: "#6c757d",   # grey
    BatchRun.STATUS_IN_PROGRESS: "#0d6efd",  # blue
    BatchRun.STATUS_ENDED: "#fd7e14",        # orange
    BatchRun.STATUS_PROCESSED: "#198754",    # green
    BatchRun.STATUS_FAILED: "#dc3545",       # red
}
_RUN_STATUS_COLORS = {
    PipelineRun.STATUS_RUNNING: "#6c757d",   # grey
    PipelineRun.STATUS_SUCCESS: "#198754",   # green
    PipelineRun.STATUS_FAILED: "#dc3545",    # red
}
_STEP_STATUS_COLORS = {
    PipelineStep.STATUS_RUNNING: "#6c757d",  # grey
    PipelineStep.STATUS_SUCCESS: "#198754",  # green
    PipelineStep.STATUS_FAILED: "#dc3545",   # red
    PipelineStep.STATUS_SKIPPED: "#adb5bd",  # light grey
}


def _badge(label, color):
    return format_html('<b style="color:{}">{}</b>', color, label)


class BatchRunInline(admin.TabularInline):
    """The batches a PipelineRun submitted (fk_name pins which of the two run
    FKs — submitted vs processed — this inline follows)."""
    model = BatchRun
    fk_name = "submitted_in_run"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("batch_id", "command", "status", "item_count",
              "success_count", "error_count", "processed_in_run")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class PipelineStepInline(admin.TabularInline):
    """The steps a cycle ran, in order — scrape / sync / extract / batch. Click a
    row to see its captured output tail."""
    model = PipelineStep
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("ordinal", "name", "status", "started_at", "finished_at", "duration")
    readonly_fields = fields
    ordering = ("ordinal",)

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="duration")
    def duration(self, obj):
        if obj.finished_at and obj.started_at:
            return f"{int((obj.finished_at - obj.started_at).total_seconds())}s"
        return "—"


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    """One row per scheduled cron cycle. The inline lists the Anthropic batches
    it submitted; ``drained`` counts batches it polled + persisted (often from
    an earlier cycle). A row stuck on ``running`` with an old ``started_at`` is
    the signal the scheduler died."""
    list_display = ("run_key", "kind", "status_badge", "started_at",
                    "finished_at", "duration", "n_submitted", "n_drained")
    list_filter = ("kind", "status")
    search_fields = ("run_key",)
    date_hierarchy = "started_at"
    readonly_fields = ("run_key", "kind", "status", "started_at", "finished_at")
    inlines = [PipelineStepInline, BatchRunInline]

    def has_add_permission(self, request):
        return False

    @admin.display(description="status", ordering="status")
    def status_badge(self, obj):
        return _badge(obj.get_status_display(), _RUN_STATUS_COLORS.get(obj.status, "#000"))

    @admin.display(description="duration")
    def duration(self, obj):
        if obj.finished_at and obj.started_at:
            return f"{int((obj.finished_at - obj.started_at).total_seconds())}s"
        return "—"

    @admin.display(description="submitted")
    def n_submitted(self, obj):
        return obj.submitted_batches.count()

    @admin.display(description="drained")
    def n_drained(self, obj):
        return obj.drained_batches.count()


@admin.register(BatchRun)
class BatchRunAdmin(admin.ModelAdmin):
    """Every Anthropic batch the pipeline submitted — find by id, filter by
    command/status/model, spot failures by the red error badge. ``submitted_in``
    vs ``processed_in`` show the drain-then-submit split (a batch is usually
    drained by a later cycle than the one that submitted it)."""
    list_display = ("batch_id", "command", "status_badge", "item_count",
                    "success_count", "error_badge", "model",
                    "submitted_at", "processed_at",
                    "submitted_in_run", "processed_in_run")
    list_filter = ("command", "status", "model")
    search_fields = ("batch_id", "submitted_in_run__run_key",
                     "processed_in_run__run_key")
    date_hierarchy = "submitted_at"
    readonly_fields = ("command", "batch_id", "model", "status", "item_count",
                       "success_count", "error_count", "errors",
                       "submitted_at", "processed_at",
                       "submitted_in_run", "processed_in_run", "updated_at")

    def has_add_permission(self, request):
        return False

    @admin.display(description="status", ordering="status")
    def status_badge(self, obj):
        return _badge(obj.get_status_display(), _BATCH_STATUS_COLORS.get(obj.status, "#000"))

    @admin.display(description="errors", ordering="error_count")
    def error_badge(self, obj):
        if obj.error_count is None:
            return "—"
        if obj.error_count:
            return _badge(obj.error_count, "#dc3545")
        return obj.error_count


@admin.register(PipelineStep)
class PipelineStepAdmin(admin.ModelAdmin):
    """Every step of every cycle — filter to all ``failed`` steps across runs, or
    search a run_key to replay one cycle's timeline. The detail page shows the
    step's captured output tail."""
    list_display = ("pipeline_run", "ordinal", "name", "status_badge",
                    "started_at", "finished_at", "duration")
    list_filter = ("name", "status")
    search_fields = ("pipeline_run__run_key", "name")
    date_hierarchy = "started_at"
    readonly_fields = ("pipeline_run", "ordinal", "name", "status",
                       "started_at", "finished_at", "metrics", "output")

    def has_add_permission(self, request):
        return False

    @admin.display(description="status", ordering="status")
    def status_badge(self, obj):
        return _badge(obj.get_status_display(), _STEP_STATUS_COLORS.get(obj.status, "#000"))

    @admin.display(description="duration")
    def duration(self, obj):
        if obj.finished_at and obj.started_at:
            return f"{int((obj.finished_at - obj.started_at).total_seconds())}s"
        return "—"


@admin.register(BillTags)
class BillTagsAdmin(admin.ModelAdmin):
    """LLM issue-area tags per bill (issue #217) — scrape-safe, unlike the OCD
    ``Bill.subject`` field these moved off of. View-only; the tagger owns them."""
    list_display = ("bill", "tags", "model_version", "generated_at", "last_regenerated")
    list_filter = ("model_version",)
    search_fields = ("bill__identifier",)
    date_hierarchy = "generated_at"
    readonly_fields = ("bill", "tags", "model_version", "tagged_batch_id",
                       "generated_at", "last_regenerated")

    def has_add_permission(self, request):
        return False

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
from opencivicdata.core.models import Person, Membership, Organization


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

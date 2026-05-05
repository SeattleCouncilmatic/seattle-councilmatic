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
    """Browse councilmembers and edit their tenure dates inline.

    Person fields are scraper-managed (name, image, sort_name, etc.)
    so they're read-only here. The MembershipInline below is where
    editorial work happens — set `start_date` / `end_date` for the
    council-seat membership and the rep detail page picks it up
    immediately."""
    list_display = ("name", "id")
    search_fields = ("name",)
    readonly_fields = ("id", "name", "sort_name", "image", "gender",
                       "biography", "birth_date", "death_date",
                       "summary", "national_identity", "family_name",
                       "given_name", "extras", "created_at", "updated_at")
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    """Direct list view of all memberships — useful for finding e.g.
    every "District N" membership at a glance and bulk-editing tenure
    dates. Most fields are scraper-managed; `start_date` and `end_date`
    are the editorial bits."""
    list_display = ("person_name", "organization_name", "label",
                    "role", "start_date", "end_date")
    list_filter = ("organization", "role")
    search_fields = ("person__name", "label")
    readonly_fields = ("id", "person", "organization", "label", "role",
                       "post", "on_behalf_of", "extras",
                       "created_at", "updated_at")
    fields = readonly_fields + ("start_date", "end_date")

    @admin.display(description="Person", ordering="person__name")
    def person_name(self, obj):
        return obj.person.name if obj.person else (obj.person_name or "")

    @admin.display(description="Organization", ordering="organization__name")
    def organization_name(self, obj):
        return obj.organization.name if obj.organization else (obj.organization_name or "")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Read-only browse — useful for confirming committee names + IDs
    when filtering memberships in the Membership admin above."""
    list_display = ("name", "classification", "id")
    list_filter = ("classification",)
    search_fields = ("name",)
    readonly_fields = ("id", "name", "classification", "parent",
                       "founding_date", "dissolution_date",
                       "image", "extras", "created_at", "updated_at")

from django.contrib.gis import admin
from .models import District, RepBio


@admin.register(RepBio)
class RepBioAdmin(admin.ModelAdmin):
    """Read-mostly admin for scraped rep bios. Edits are allowed so
    curators can fix extraction artifacts, but the next
    ``scrape_rep_bios`` run will overwrite them — `scraped_at` shows
    when that's likely to happen next."""

    list_display = ("person", "source_url", "scraped_at")
    search_fields = ("person__name",)
    readonly_fields = ("scraped_at", "created_at")
    fields = ("person", "bio", "source_url", "scraped_at", "created_at")


@admin.register(District)
class DistrictAdmin(admin.GISModelAdmin):
    """
    Admin interface for City Council Districts.

    GISModelAdmin provides a map widget for viewing/editing geometries.
    """

    # Fields to display in the district list view
    list_display = ['number', 'name', 'created_at']

    # Fields you can search by
    search_fields = ['number', 'name']

    # Default ordering
    ordering = ['number']

    # Read-only fields (can't edit these)
    readonly_fields = ['created_at', 'updated_at']

    # GeoDjango map settings
    # These control the interactive map in the admin
    default_zoom = 11  # Zoom level (higher = more zoomed in)
    default_lon = -122.3321  # Seattle longitude (center map here)
    default_lat = 47.6062    # Seattle latitude

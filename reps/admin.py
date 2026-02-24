from django.contrib.gis import admin
from .models import District


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

from django.contrib.gis.db import models


class District(models.Model):
    """
    Represents a Seattle City Council district with its geographic boundary.

    Seattle has 7 district-based council seats (Districts 1-7) and
    2 citywide "At Large" positions.
    """

    # District number (1-7) or "At Large"
    number = models.CharField(
        max_length=10,
        unique=True,
        help_text="District number (1-7) or 'At Large'"
    )

    # Human-readable name
    name = models.CharField(
        max_length=100,
        help_text="e.g., 'District 1' or 'Citywide At Large'"
    )

    # Geographic boundary
    # MultiPolygonField stores geographic shapes (district boundaries)
    # SRID 4326 = WGS 84 (standard GPS coordinates, latitude/longitude)
    geometry = models.MultiPolygonField(
        srid=4326,
        help_text="District boundary polygon(s)"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']
        verbose_name = "City Council District"
        verbose_name_plural = "City Council Districts"

    def __str__(self):
        return self.name

    def contains_point(self, latitude, longitude):
        """
        Check if a given point (address coordinates) falls within this district.

        Args:
            latitude: float
            longitude: float

        Returns:
            bool: True if point is in this district
        """
        from django.contrib.gis.geos import Point

        point = Point(longitude, latitude, srid=4326)
        return self.geometry.contains(point)
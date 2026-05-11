from django.contrib.gis.db import models


class RepBio(models.Model):
    """Biographical prose scraped from a council member's seattle.gov
    ``/about-<firstname>`` page. One row per person.

    Kept as raw text rather than split into ``education`` /
    ``professional_background`` columns — bio shape varies across
    reps, and the LLM summary pipeline (issue #147 / Phase 2) extracts
    structured pieces at synthesis time. That keeps re-scrapes cheap
    (whole-prose UPSERT) and lets the prompt evolve without schema
    churn.

    Re-scraping is idempotent — ``scrape_rep_bios`` re-runs UPSERT
    by ``person_id``."""

    person = models.OneToOneField(
        "core.Person",
        on_delete=models.CASCADE,
        related_name="rep_bio",
        help_text="OCD Person this bio belongs to.",
    )
    bio = models.TextField(
        help_text="Biographical prose, paragraphs joined with '\\n\\n'.",
    )
    source_url = models.URLField(
        max_length=500,
        help_text="seattle.gov URL the bio was scraped from.",
    )
    scraped_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time the bio was (re-)scraped.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Rep biographical text"
        verbose_name_plural = "Rep biographical texts"

    def __str__(self):
        return f"Bio for {self.person.name}"


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

    # Short description of the area represented (e.g. "Representing Ballard, Fremont, and Green Lake")
    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Short description of the neighborhoods/area this district covers"
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
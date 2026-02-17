import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry
from reps.models import District


class Command(BaseCommand):
    """
    Django management command to load Seattle City Council district boundaries
    from GeoJSON into the database.

    Usage:
        python manage.py load_districts

    Or in Docker:
        docker exec seattle_councilmatic python manage.py load_districts
    """

    help = "Load Seattle City Council district boundaries from GeoJSON"

    def handle(self, *args, **options):
        """Main command logic"""

        # Path to the GeoJSON file
        geojson_path = Path(__file__).parent.parent.parent / "data" / "districts.geojson"

        if not geojson_path.exists():
            self.stdout.write(
                self.style.ERROR(f"GeoJSON file not found: {geojson_path}")
            )
            return

        self.stdout.write(f"Loading districts from {geojson_path}...")

        # Read the GeoJSON file
        with open(geojson_path, "r") as f:
            geojson_data = json.load(f)

        # Counter for tracking progress
        created_count = 0
        updated_count = 0

        # Process each feature (district) in the GeoJSON
        for feature in geojson_data["features"]:
            # Extract district number from properties
            district_num = feature["properties"]["COUNCIL_DIST"]

            # Create human-readable name
            district_name = f"District {district_num}"

            # Extract geometry
            # GEOSGeometry converts GeoJSON geometry to PostGIS format
            geometry = GEOSGeometry(json.dumps(feature["geometry"]))

            # Create or update the district
            # update_or_create: updates if exists, creates if not
            district, created = District.objects.update_or_create(
                number=str(district_num),
                defaults={
                    "name": district_name,
                    "geometry": geometry,
                }
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Created {district_name}")
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f"  ↻ Updated {district_name}")
                )

        # Summary
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created: {created_count}, Updated: {updated_count}"
            )
        )

        # Show total count
        total = District.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f"Total districts in database: {total}")
        )

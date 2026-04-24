from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.db import connection
from opencivicdata.core.models import Person as OCDPerson
from councilmatic_core.models import Person as CouncilPerson


class Command(BaseCommand):
    help = "Sync OCD data to Councilmatic models (Person, Organization, etc.)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            type=str,
            default="all",
            help="Which model to sync: people, organizations, or all",
        )

    def handle(self, *args, **options):
        model = options["model"]

        if model in ["people", "all"]:
            self.sync_people()

        if model in ["events", "all"]:
            self.sync_events()

        if model in ["bills", "all"]:
            self.sync_bills()

        if model in ["organizations", "all"]:
            self.stdout.write("Organization sync not yet implemented")

        self.stdout.write(self.style.SUCCESS("\n✓ Sync complete!"))

    def sync_people(self):
        self.stdout.write("\nSyncing people...")

        # Use raw SQL for reliability
        with connection.cursor() as cursor:
            # Mark all people as not current initially
            cursor.execute(
                """
                UPDATE councilmatic_core_person SET is_current = FALSE
            """
            )

            # Mark the most recent person for each position as current
            # This handles transitions like Sara Nelson -> Dionne Foster in Position 9
            # Uses label field (e.g., "District 4", "Position 9") to identify positions
            cursor.execute(
                """
                UPDATE councilmatic_core_person
                SET is_current = TRUE
                WHERE person_id IN (
                    SELECT person_id
                    FROM (
                        SELECT DISTINCT
                            p.id as person_id,
                            ROW_NUMBER() OVER (
                                PARTITION BY m.label
                                ORDER BY p.created_at DESC, p.id DESC
                            ) as rn
                        FROM opencivicdata_person p
                        INNER JOIN opencivicdata_membership m ON m.person_id = p.id
                        INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
                        WHERE o.name = 'Seattle City Council'
                          AND m.label IS NOT NULL
                    ) ranked
                    WHERE rn = 1
                )
            """
            )

            marked_current = cursor.rowcount

            # Insert new people (only current ones)
            cursor.execute(
                """
                INSERT INTO councilmatic_core_person (person_id, slug, headshot, councilmatic_biography, is_current)
                SELECT
                    person_id,
                    slug,
                    '' as headshot,
                    NULL as councilmatic_biography,
                    TRUE as is_current
                FROM (
                    SELECT DISTINCT
                        p.id as person_id,
                        lower(regexp_replace(p.name, '[^a-zA-Z0-9]+', '-', 'g')) as slug,
                        ROW_NUMBER() OVER (
                            PARTITION BY m.label
                            ORDER BY p.created_at DESC, p.id DESC
                        ) as rn
                    FROM opencivicdata_person p
                    INNER JOIN opencivicdata_membership m ON m.person_id = p.id
                    INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
                    WHERE o.name = 'Seattle City Council'
                      AND m.label IS NOT NULL
                ) ranked
                WHERE rn = 1
                  AND person_id NOT IN (SELECT person_id FROM councilmatic_core_person)
                ON CONFLICT (person_id) DO NOTHING
            """
            )

            created = cursor.rowcount

            # Get counts
            cursor.execute("SELECT COUNT(*) FROM councilmatic_core_person WHERE is_current = TRUE")
            current_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM councilmatic_core_person WHERE is_current = FALSE")
            former_count = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(f"  ✓ People: {created} created, {current_count} current, {former_count} former")
        )

    def sync_events(self):
        self.stdout.write("\nSyncing events...")

        # Use raw SQL for reliability
        with connection.cursor() as cursor:
            # Insert with conflict handling
            # Make slug unique by appending start date
            cursor.execute(
                """
                INSERT INTO councilmatic_core_event (event_id, slug)
                SELECT
                    id as event_id,
                    lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))
                        || '-' || to_char(start_date::timestamp, 'YYYY-MM-DD-HH24-MI-SS') as slug
                FROM opencivicdata_event
                WHERE id NOT IN (SELECT event_id FROM councilmatic_core_event)
                ON CONFLICT (event_id) DO NOTHING
            """
            )

            created = cursor.rowcount

            # Get total count
            cursor.execute("SELECT COUNT(*) FROM councilmatic_core_event")
            total = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(f"  ✓ Events: {created} created, {total} total")
        )

    def sync_bills(self):
        self.stdout.write("\nSyncing bills...")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO councilmatic_core_bill (
                    bill_id, 
                    slug,
                    restrict_view
                )
                SELECT
                    b.id as bill_id,
                    lower(regexp_replace(b.identifier, '[^a-zA-Z0-9]+', '-', 'g')) as slug,
                    false as restrict_view
                FROM opencivicdata_bill b
                WHERE b.id NOT IN (SELECT bill_id FROM councilmatic_core_bill)
                ON CONFLICT (bill_id) DO NOTHING
            """
            )
            created = cursor.rowcount

            cursor.execute("SELECT COUNT(*) FROM councilmatic_core_bill")
            total = cursor.fetchone()[0]

            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Bills: {created} created, {total} total")
            )

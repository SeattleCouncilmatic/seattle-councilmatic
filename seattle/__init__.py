from pupa.scrape import Jurisdiction, Organization
from .people import SeattlePersonScraper
from .events import SeattleEventScraper
from .bills import SeattleBillScraper

# TODO: Implement these scrapers
# from .vote_events import SeattleVoteEventScraper

class Seattle(Jurisdiction):
    # These IDs are from Open Civic Data standard and identify Seattle
    division_id = "ocd-division/country:us/state:wa/place:seattle"
    classification = "legislature"
    name = "Seattle City Council"
    url = "https://www.seattle.gov/council"

    #Registers all available scrapers
    scrapers = {
        "people": SeattlePersonScraper,
        "events": SeattleEventScraper,
        "bills": SeattleBillScraper,
        # TODO: Add these back when implemented
        # "vote_events": SeattleVoteEventScraper,
    }

    # Bills must be linked to a legislative session
    # If session doesn't exist, import fails with foreign key error
    legislative_sessions = [
        {
            "identifier": "2025",
            "name": "2025 Legislative Session",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        },
        # Add other years as needed
    ]
    
    # Defines the structure of Seattle City Council
    # This creates the "seats" that people hold
    def get_organizations(self):
        org = Organization(
            name="Seattle City Council",
            classification="legislature"
        )

        # Seattle has 7 district-based seats
        # Add district seats (7 districts)
        for i in range(1, 8):
            org.add_post(
                label=f"District {i}",
                role="Councilmember"
            )

        # Seattle has 2 at-large seats (positions 8 and 9)
        # Add at-large positions (2 positions)
        for i in range(8, 10):
            org.add_post(
                label=f"Position {i}",
                role="Councilmember"
            )

        yield org
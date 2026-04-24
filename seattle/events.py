"""
Seattle City Council Events Scraper

This scraper fetches meeting/event data from Seattle's Legistar API
and converts it into Pupa's Event model format for Open Civic Data.

Learning Goals:
- Working with REST APIs using requests library
- Date/time handling with datetime and pytz
- Python list comprehensions and generator patterns
- Pupa's Event model structure
"""

from pupa.scrape import Scraper, Event
import requests
import datetime
import pytz
import logging

# Set up logging to help with debugging
# This is a Python best practice - better than using print() statements
logger = logging.getLogger(__name__)


class SeattleEventScraper(Scraper):
    """
    Scrapes Seattle City Council events (meetings) from Legistar API.
    
    Python Class Concepts:
    - Inherits from Pupa's Scraper class (that's what 'Scraper' in parentheses means)
    - The scrape() method is required by Pupa - it's like an interface contract
    - Class variables (below) are shared across all instances
    """
    
    # Base URL for Seattle's Legistar API
    # Using a class variable makes it easy to change if the API changes
    BASE_URL = "https://webapi.legistar.com/v1/seattle"
    
    # Seattle's timezone - crucial for converting timestamps correctly
    # pytz is the standard Python library for timezone handling
    TIMEZONE = pytz.timezone("America/Los_Angeles")
    
    # Start scraping from 2019 (as discussed)
    # We'll filter API requests to only get events from this year forward
    START_YEAR = 2019
    
    # Event items to ignore (procedural, not substantive)
    # Python convention: ALL_CAPS for constants that shouldn't change
    IGNORE_PATTERNS = [
        "CALL TO ORDER",
        "ROLL CALL",
        "APPROVAL OF",
        "ADJOURNMENT",
        "RECESS",
    ]
    
    def scrape(self):
        """
        Main scraping method - required by Pupa.

        This method is a Python generator (uses 'yield' instead of 'return').
        Generators are memory-efficient - they produce items one at a time
        instead of loading everything into memory at once.

        Yields:
            Event objects that Pupa will validate and save
        """

        # Step 1: Get all events from Legistar
        events = self._fetch_events()

        # Track seen events to avoid duplicates
        # Use a set of (name, date) tuples for fast lookup
        seen_events = set()

        # Step 2: Process each event
        for api_event in events:
            # Create a unique key for deduplication
            event_key = (
                api_event.get('EventBodyName', 'Meeting'),
                api_event['EventDate']
            )

            # Skip if we've already seen this event
            if event_key in seen_events:
                logger.debug(f"Skipping duplicate event: {event_key}")
                continue

            # Mark as seen
            seen_events.add(event_key)

            # Convert Legistar API event to Pupa Event model
            event = self._parse_event(api_event)

            # Only yield if we successfully created an event
            if event:
                yield event
    
    def _fetch_events(self):
        """
        Fetch events from Legistar API with date filtering.
        
        Python Convention: Methods starting with _ are "private"
        (not enforced, just a naming convention to signal intent)
        
        Returns:
            List of event dictionaries from the API
        """
        
        # Build the API endpoint URL
        url = f"{self.BASE_URL}/events"
        
        # Use a rolling window: 3 months back through 6 months ahead.
        # This keeps the result set small enough that pupa won't hit a page
        # cap before reaching future-dated events.
        today = datetime.datetime.utcnow()
        window_start = today - datetime.timedelta(days=90)
        window_end   = today + datetime.timedelta(days=180)

        # OData query parameters for filtering
        # Legistar uses OData protocol (like SQL for REST APIs)
        # The $ prefix is OData convention
        params = {
            "$filter": (
                f"EventDate ge datetime'{window_start.strftime('%Y-%m-%d')}'"
                f" and EventDate le datetime'{window_end.strftime('%Y-%m-%d')}'"
            ),
            "$orderby": "EventDate asc",
        }
        
        # Make the API request
        # Try/except is Python's error handling - similar to C#'s try/catch
        try:
            # requests.get() is the standard way to make HTTP GET requests in Python
            # timeout=30 prevents hanging forever if the API is slow
            response = requests.get(url, params=params, timeout=30)
            
            # Raise an exception if we got an error status code (4xx, 5xx)
            # This will jump to the 'except' block below
            response.raise_for_status()
            
            # Parse JSON response
            # .json() automatically converts JSON string to Python dict/list
            events = response.json()
            
            # Log success for debugging
            # f-strings (f"...{variable}...") are Python 3.6+ string formatting
            logger.info(f"Fetched {len(events)} events from Legistar API")
            
            return events
            
        except requests.exceptions.RequestException as e:
            # Log the error - don't crash, just warn
            # This is more robust than letting the scraper die
            logger.error(f"Failed to fetch events from Legistar: {e}")
            
            # Return empty list so the scraper can continue
            # Python idiom: it's often better to return empty collections than None
            return []
    
    def _parse_event(self, api_event):
        """
        Convert a Legistar API event dict into a Pupa Event object.
        
        Args:
            api_event: Dictionary from Legistar API
            
        Returns:
            Event object or None if parsing fails
        """
        
        try:
            # Extract required fields from API response
            # Python dict access: api_event['key'] raises error if missing
            # api_event.get('key') returns None if missing (safer)
            event_id = api_event['EventId']
            event_name = api_event.get('EventBodyName', 'Meeting')
            event_date_str = api_event['EventDate']
            location = api_event.get('EventLocation', 'Location TBD')

            # Parse the date string into a Python datetime object
            # strptime = "string parse time"
            # The format string tells Python how to interpret the date string
            event_date = datetime.datetime.strptime(
                event_date_str,
                "%Y-%m-%dT%H:%M:%S"  # Format from Legistar
            )

            # Localize to Seattle timezone
            # Without this, the datetime is "naive" (no timezone info)
            event_date = self.TIMEZONE.localize(event_date)

            # Create Pupa Event object
            # This is the core Open Civic Data model
            event = Event(
                name=event_name,
                start_date=event_date,
                location_name=location,
            )

            # Store the Legistar event ID in extras for tracking
            event.extras['legistar_event_id'] = event_id
            
            # Add source URL for transparency/debugging
            # Legistar provides a web page for each event
            if api_event.get('EventInSiteURL'):
                event.add_source(api_event['EventInSiteURL'])

            # Note: Event objects don't have add_identifier() method
            # Pupa uses the source URL and event details for deduplication instead
            
            # TODO: Add agenda items (we'll implement this next)
            # self._add_agenda_items(event, event_id)
            
            logger.info(f"Parsed event: {event_name} on {event_date.date()}")
            
            return event
            
        except (KeyError, ValueError) as e:
            # KeyError: missing required field in API response
            # ValueError: date parsing failed
            logger.warning(f"Failed to parse event {api_event.get('EventId')}: {e}")
            return None


# ============================================================================
# NEXT STEPS TO IMPLEMENT:
# ============================================================================
#
# 1. Add _add_agenda_items() method to fetch and add agenda items
# 2. Add _should_include_agenda_item() to filter out procedural items
# 3. Test with: docker compose run --rm app pupa update seattle events --scrape
# 4. Once working, register in seattle/__init__.py
#
# ============================================================================
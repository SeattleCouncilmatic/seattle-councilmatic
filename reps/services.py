"""
Service layer for representative lookup functionality.

This module handles:
- Geocoding addresses to coordinates
- Finding which district contains an address
- Looking up representatives for a district
"""

from typing import Optional, Dict, Any, List
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from django.contrib.gis.geos import Point
from django.db import models
from councilmatic_core.models import Person, Membership
from .models import District


class GeocodingService:
    """
    Handles address geocoding using OpenStreetMap's Nominatim service.

    Nominatim is free and doesn't require an API key, but has rate limits.
    For production, consider caching results or using a paid service.
    """

    def __init__(self):
        # User agent is required by Nominatim terms of service
        # Should be something that identifies your app
        self.geolocator = Nominatim(
            user_agent="seattle_councilmatic",
            timeout=10
        )

    def geocode_address(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Convert an address string to geographic coordinates.

        Args:
            address: Street address (e.g., "123 Main St, Seattle, WA")

        Returns:
            Dict with 'latitude', 'longitude', 'formatted_address', or None if not found

        Example:
            >>> service = GeocodingService()
            >>> result = service.geocode_address("Seattle City Hall, Seattle, WA")
            >>> print(result)
            {
                'latitude': 47.6043,
                'longitude': -122.3301,
                'formatted_address': 'Seattle City Hall, 600 4th Ave, Seattle, WA 98104'
            }
        """
        try:
            # Add "Seattle, WA" to address if not already present
            # This helps improve accuracy for local addresses
            if "seattle" not in address.lower():
                address = f"{address}, Seattle, WA"

            location = self.geolocator.geocode(address)

            if location:
                return {
                    'latitude': location.latitude,
                    'longitude': location.longitude,
                    'formatted_address': location.address
                }

            return None

        except GeocoderTimedOut:
            # Handle timeout - could retry or return None
            return None

        except GeocoderServiceError as e:
            # Handle service errors (API down, etc.)
            print(f"Geocoding service error: {e}")
            return None


class DistrictLookupService:
    """
    Handles finding which council district contains a given address or coordinates.
    """

    def find_district_by_address(self, address: str) -> Optional[District]:
        """
        Find which council district contains the given address.

        Args:
            address: Street address to look up

        Returns:
            District object if found, None otherwise

        Example:
            >>> service = DistrictLookupService()
            >>> district = service.find_district_by_address("Seattle City Hall")
            >>> print(district.name)
            'District 7'
        """
        # First, geocode the address
        geocoding_service = GeocodingService()
        location = geocoding_service.geocode_address(address)

        if not location:
            return None

        # Then find the district
        return self.find_district_by_coordinates(
            location['latitude'],
            location['longitude']
        )

    def find_district_by_coordinates(
        self,
        latitude: float,
        longitude: float
    ) -> Optional[District]:
        """
        Find which council district contains the given coordinates.

        This uses PostGIS's spatial query capabilities - very efficient!

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            District object if found, None otherwise

        Example:
            >>> service = DistrictLookupService()
            >>> district = service.find_district_by_coordinates(47.6062, -122.3321)
            >>> print(district.name)
            'District 7'
        """
        # Create a Point from the coordinates
        # Note: PostGIS uses (longitude, latitude) order, not (lat, long)!
        point = Point(longitude, latitude, srid=4326)

        # Query the database for a district that contains this point
        # This uses PostGIS's ST_Contains function under the hood
        try:
            district = District.objects.filter(geometry__contains=point).first()
            return district
        except Exception as e:
            print(f"Database error during district lookup: {e}")
            return None


class RepLookupService:
    """
    High-level service that combines geocoding and district lookup
    to find representatives for an address.
    """

    def __init__(self):
        self.district_service = DistrictLookupService()

    def lookup_by_address(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Complete lookup: address → coordinates → district → representatives

        Args:
            address: Street address to look up

        Returns:
            Dict with district info and representatives, or None if not found

        Example:
            >>> service = RepLookupService()
            >>> result = service.lookup_by_address("Seattle City Hall")
            >>> print(result)
            {
                'district': {
                    'number': '7',
                    'name': 'District 7'
                },
                'representatives': [...]
            }
        """
        # Find the district
        district = self.district_service.find_district_by_address(address)

        if not district:
            return None

        # Fetch representatives for this district
        representatives = self._get_representatives_for_district(district.number)

        # Convert geometry to GeoJSON for frontend mapping
        import json
        geometry_geojson = json.loads(district.geometry.geojson) if district.geometry else None

        return {
            'district': {
                'number': district.number,
                'name': district.name,
                'geometry': geometry_geojson
            },
            'representatives': representatives
        }

    def _get_representatives_for_district(self, district_number: str) -> List[Dict[str, Any]]:
        """
        Get CURRENT council members representing the given district.

        Includes both district-specific representative AND at-large representatives
        (Position 8 and Position 9) who represent the entire city.

        Only returns currently serving council members (is_current=True).

        Args:
            district_number: District number (1-7) or "At Large"

        Returns:
            List of representative info dicts

        Example:
            >>> service = RepLookupService()
            >>> reps = service._get_representatives_for_district("7")
            >>> print(reps)
            [
                {'name': 'Robert Kettle', 'role': 'Councilmember', 'district': 'District 7', ...},
                {'name': 'Dionne Foster', 'role': 'Councilmember', 'district': 'Position 9', ...},
                {'name': 'Alexis Mercedes Rinck', 'role': 'Councilmember', 'district': 'Position 8', ...}
            ]
        """
        # Query for district-specific representative
        district_label = f"District {district_number}"

        # Also get at-large representatives (Position 8 and Position 9)
        # They represent the entire city
        # Filter by is_current to only get currently serving members
        from django.db import connection

        # Use raw SQL to join with councilmatic_core_person and filter by is_current
        # This is necessary because is_current is a dynamically added column
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT
                    p.name,
                    m.role,
                    m.label,
                    p.id as person_id
                FROM opencivicdata_membership m
                INNER JOIN opencivicdata_person p ON m.person_id = p.id
                INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
                INNER JOIN councilmatic_core_person cp ON cp.person_id = p.id
                WHERE o.name = 'Seattle City Council'
                  AND cp.is_current = TRUE
                  AND (m.label = %s OR m.label LIKE 'Position%%')
                ORDER BY m.label
            """, [district_label])

            representatives = []
            for row in cursor.fetchall():
                name, role, label, person_id = row

                # Get the Person object for additional details
                from opencivicdata.core.models import Person as OCDPerson
                person = OCDPerson.objects.get(id=person_id)

                rep_data = {
                    'name': name,
                    'role': role,
                    'district': label,
                }

                # Add contact details if available
                contact_details = person.contact_details.all()
                for contact in contact_details:
                    if contact.type == 'email':
                        rep_data['email'] = contact.value
                    elif contact.type == 'voice':
                        rep_data['phone'] = contact.value

                # Add links if available
                links = person.links.all()
                for link in links:
                    if link.note == 'City Council profile':
                        rep_data['profile_url'] = link.url

                representatives.append(rep_data)

        return representatives

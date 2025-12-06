"""
Service layer for representative lookup functionality.

This module handles:
- Geocoding addresses to coordinates
- Finding which district contains an address
- Looking up representatives for a district
"""

from typing import Optional, Dict, Any
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from django.contrib.gis.geos import Point
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

        # TODO: Once we integrate with Person model, fetch actual representatives
        # For now, just return district info
        return {
            'district': {
                'number': district.number,
                'name': district.name
            },
            'representatives': []  # Will populate this next
        }

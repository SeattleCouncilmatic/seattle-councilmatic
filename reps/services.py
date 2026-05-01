"""
Service layer for representative lookup functionality.

This module handles:
- Geocoding addresses to coordinates
- Finding which district contains an address
- Looking up representatives for a district
- Listing districts and at-large reps for the council overview map
"""

import json
from typing import Optional, Dict, Any, List

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from django.contrib.gis.geos import Point
from django.db import connection, models

from councilmatic_core.models import Bill, Person, Membership
from django.db.models import Max
from .models import District


# Default simplification tolerance for the council overview map. ~5m at
# Seattle's latitude — invisible at the rendered zoom level. The
# unsimplified geometry stays in the DB for ST_Contains lookups.
_OVERVIEW_SIMPLIFY_TOLERANCE = 0.00005


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
                'description': district.description,
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

                # Look up district description for this label
                district_description = ''
                try:
                    if label.startswith('District '):
                        d = District.objects.filter(number=label.split(' ')[1]).first()
                    else:
                        d = District.objects.filter(number='At Large').first()
                    if d:
                        district_description = d.description
                except Exception:
                    pass

                rep_data = {
                    'name': name,
                    'role': role,
                    'district': label,
                    'district_description': district_description,
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


# ---------------------------------------------------------------------------
# Council overview map endpoints
# ---------------------------------------------------------------------------


def _rep_row_to_dict(name: str, slug: str, label: str, person_id: str) -> Dict[str, Any]:
    """Build the canonical rep dict from a (name, slug, membership_label,
    person_id) row. Pulls contact details and links from opencivicdata
    via the Person primary key. Used by both /api/reps/ list endpoints
    and /api/reps/<slug>/ detail."""
    from opencivicdata.core.models import Person as OCDPerson

    rep_data = {
        'name': name,
        'slug': slug,
        'role': 'Councilmember',
        'district': label,
    }

    # Add the District.description (if a District row matches the membership label)
    try:
        if label.startswith('District '):
            d = District.objects.filter(number=label.split(' ')[1]).first()
        elif label.startswith('Position '):
            d = District.objects.filter(number='At Large').first()
        else:
            d = None
        if d:
            rep_data['district_description'] = d.description
    except Exception:
        pass

    # Filter by Person primary key (unique) instead of membership label
    # — the latter has collisions across former and current holders of
    # the same seat (e.g. both Sara Nelson and Dionne Foster have held
    # Position 9, so a label-based .first() can return the wrong one
    # and pull her predecessor's contact info).
    person = OCDPerson.objects.filter(id=person_id).first()
    if person:
        for contact in person.contact_details.all():
            if contact.type == 'email':
                rep_data['email'] = contact.value
            elif contact.type == 'voice':
                rep_data['phone'] = contact.value
        for link in person.links.all():
            if link.note == 'City Council profile':
                rep_data['profile_url'] = link.url
            elif link.note == 'Office Hours':
                rep_data['office_hours_url'] = link.url

    return rep_data


def _query_current_council_members(extra_filter: str = "", params: Optional[List] = None
                                   ) -> List[tuple]:
    """Returns [(name, slug, membership_label, person_id), ...] for
    currently serving council members. Centralized so both list and
    detail endpoints share the same filter (cp.is_current = TRUE plus
    the org join). is_current lives on councilmatic_core_person via a
    raw-SQL ALTER (see seattle_app/migrations/0001_add_is_current_to_person.py),
    which is why we drop to raw SQL instead of using the ORM."""
    base = """
        SELECT DISTINCT p.name, cp.slug, m.label, p.id
        FROM opencivicdata_membership m
        INNER JOIN opencivicdata_person p ON m.person_id = p.id
        INNER JOIN opencivicdata_organization o ON m.organization_id = o.id
        INNER JOIN councilmatic_core_person cp ON cp.person_id = p.id
        WHERE o.name = 'Seattle City Council'
          AND cp.is_current = TRUE
    """
    sql = base + extra_filter + " ORDER BY m.label"
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def list_districts_with_reps(simplify_tolerance: float = _OVERVIEW_SIMPLIFY_TOLERANCE
                             ) -> List[Dict[str, Any]]:
    """All 7 numbered districts with simplified GeoJSON geometry and the
    current rep for each. Geometry simplification is purely a payload
    optimization — address lookup uses the unsimplified DB geometry, so
    visual simplification can never route an address to the wrong rep."""
    rep_lookup = {label: (name, slug, person_id) for name, slug, label, person_id in
                  _query_current_council_members(
                      extra_filter=" AND m.label LIKE 'District %%'"
                  )}

    out = []
    for d in District.objects.exclude(number='At Large').order_by('number'):
        membership_label = f'District {d.number}'
        rep = None
        if membership_label in rep_lookup:
            name, slug, person_id = rep_lookup[membership_label]
            rep = _rep_row_to_dict(name, slug, membership_label, person_id)
        # Python-side simplify via GEOS — preserve_topology=True keeps the
        # polygon valid (no self-intersections) at our tolerance, which
        # could otherwise corrupt rendering of complex coastline shapes.
        simple = d.geometry.simplify(tolerance=simplify_tolerance, preserve_topology=True)
        out.append({
            'number':      d.number,
            'name':        d.name,
            'description': d.description,
            'geometry':    json.loads(simple.geojson) if simple else None,
            'rep':         rep,
        })
    return out


def list_at_large_reps() -> List[Dict[str, Any]]:
    """The 2 at-large reps (Position 8 + Position 9). No geometry — they
    represent the whole city, so they're rendered as cards beside the map
    rather than as polygons on it."""
    rows = _query_current_council_members(extra_filter=" AND m.label LIKE 'Position %%'")
    return [_rep_row_to_dict(name, slug, label, pid)
            for name, slug, label, pid in rows]


def get_rep_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Single rep detail by councilmatic_core_person.slug. Returns None
    for unknown slugs or for reps who aren't currently serving. Includes
    a `sponsored_bills` list (most recent activity first, capped) and
    `sponsored_bills_total` so the detail page can surface a "view all"
    link when the rep has more bills than we ship inline."""
    rows = _query_current_council_members(
        extra_filter=" AND cp.slug = %s",
        params=[slug],
    )
    if not rows:
        return None
    name, slug_back, label, person_id = rows[0]
    rep = _rep_row_to_dict(name, slug_back, label, person_id)
    bills, total = _get_sponsored_bills(name)
    rep['sponsored_bills'] = bills
    rep['sponsored_bills_total'] = total
    return rep


# Mirrors `_normalise_status` in seattle_app/api_views.py — same status
# label + variant pair the legislation index uses on its cards. Imported
# at call time so a circular `seattle_app -> reps -> seattle_app` import
# during module init can't form (reps loads early; seattle_app builds
# views that import from reps).
def _normalise_status_lazy(raw: str) -> tuple[str, str]:
    from seattle_app.api_views import _normalise_status
    return _normalise_status(raw)


def _get_sponsored_bills(rep_name: str, limit: int = 10
                         ) -> tuple[List[Dict[str, Any]], int]:
    """Return up to `limit` bills sponsored by `rep_name` (most recent
    activity first), plus the total count of all sponsored bills. Each
    row matches the shape `LegislationCard.jsx` expects so the existing
    card component renders them on `/reps/<slug>/`; the total powers a
    "View all" link to the legislation index when `limit` is exceeded.
    `is_primary` flags bills where the rep is a primary sponsor (vs.
    cosponsor)."""
    if not rep_name:
        return [], 0

    base = (
        Bill.objects
        .filter(sponsorships__name__iexact=rep_name)
        .distinct()
    )
    total = base.count()
    bills = (
        base
        .annotate(latest_action_date=Max('actions__date'))
        .order_by('-latest_action_date', '-identifier')
        .prefetch_related('sponsorships', 'actions')
        [:limit]
    )

    rep_name_lower = rep_name.lower()
    results: List[Dict[str, Any]] = []
    for bill in bills:
        is_primary = any(
            s.primary and (s.entity_name or '').lower() == rep_name_lower
            for s in bill.sponsorships.all()
        )
        # Earliest action date doubles as introduced date — same heuristic
        # as legislation_index. Action `date` strings are ISO 8601 with
        # optional time; slice to the YYYY-MM-DD prefix for display.
        dates = [a.date for a in bill.actions.all() if a.date]
        intro_date = min(dates)[:10] if dates else None
        raw_status = bill.extras.get('MatterStatusName', '')
        status_label, status_variant = _normalise_status_lazy(raw_status)
        results.append({
            'identifier':      bill.identifier,
            'title':           bill.title,
            'slug':            bill.slug,
            'status':          status_label,
            'status_variant': status_variant,
            'date_introduced': intro_date,
            'is_primary':      is_primary,
        })
    return results, total


def get_district_with_reps(number: str) -> Optional[Dict[str, Any]]:
    """Combined payload for /reps/district/<number>: the district rep
    plus both at-large reps (who represent every district), plus the
    district's simplified GeoJSON geometry for the close-up map on the
    detail page. Returns None if the district doesn't exist. Numeric
    districts only — the catch-all 'At Large' District row isn't a valid
    argument here."""
    if number == 'At Large':
        return None
    try:
        district = District.objects.get(number=number)
    except District.DoesNotExist:
        return None

    district_rep = None
    rows = _query_current_council_members(
        extra_filter=" AND m.label = %s",
        params=[f'District {number}'],
    )
    if rows:
        district_rep = _rep_row_to_dict(*rows[0])

    # Same simplification as the overview map — fine enough at the
    # zoomed-in single-district view that artifacts aren't visible.
    simple_geom = district.geometry.simplify(
        tolerance=_OVERVIEW_SIMPLIFY_TOLERANCE, preserve_topology=True
    )

    return {
        'district': {
            'number':      district.number,
            'name':        district.name,
            'description': district.description,
            'geometry':    json.loads(simple_geom.geojson) if simple_geom else None,
        },
        'rep':      district_rep,
        'at_large': list_at_large_reps(),
    }

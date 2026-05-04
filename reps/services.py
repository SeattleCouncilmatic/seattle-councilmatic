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
from opencivicdata.legislative.models import PersonVote
from django.db.models import Count, Max
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
        if person.image:
            rep_data['image'] = person.image
        # Staff list lives on `Person.extras['staff']` as a JSON list
        # of `{name, title, email}` dicts — see seattle/people.py.
        staff = (person.extras or {}).get('staff') or []
        if staff:
            rep_data['staff'] = staff
        for contact in person.contact_details.all():
            if contact.type == 'email':
                rep_data['email'] = contact.value
            elif contact.type == 'voice':
                rep_data['phone'] = contact.value
            elif contact.type == 'fax':
                rep_data['fax'] = contact.value
            elif contact.type == 'address':
                # Two address rows per person (Office + Mailing) keyed by
                # `note` — see seattle/people.py.
                if contact.note == 'Office':
                    rep_data['office_address'] = contact.value
                elif contact.note == 'Mailing':
                    rep_data['mailing_address'] = contact.value
        for link in person.links.all():
            if link.note == 'City Council profile':
                rep_data['profile_url'] = link.url
            elif link.note == 'Office Hours':
                rep_data['office_hours_url'] = link.url

        # Committee memberships — one entry per committee Org. Sort
        # by role priority (Chair > Vice-Chair > Member) so the most
        # senior assignments lead, then by committee name. Each entry
        # carries the committee Organization id (for future linking
        # to per-committee detail pages) plus the seattle.gov source
        # URL for now.
        rep_data['committees'] = _committees_for_person(person)

    return rep_data


_COMMITTEE_ROLE_ORDER = {"Chair": 0, "Vice-Chair": 1, "Member": 2}


def _committees_for_person(person) -> List[Dict[str, Any]]:
    rows: list[dict] = []
    qs = person.memberships.filter(
        organization__classification="committee"
    ).select_related("organization").prefetch_related("organization__sources")
    for m in qs:
        org = m.organization
        source_url = None
        sources = list(org.sources.all())
        if sources:
            source_url = sources[0].url
        rows.append({
            "name": org.name,
            "role": m.role,
            "organization_id": org.id,
            "source_url": source_url,
        })
    rows.sort(key=lambda r: (_COMMITTEE_ROLE_ORDER.get(r["role"], 99), r["name"]))
    return rows


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
    rep['voting_history'] = _get_voting_history(person_id)
    rep['legislation_involvement'] = _get_legislation_involvement(person_id, name)
    return rep


# Pupa's standard vote-option keys → display labels. The keys come from
# `seattle/vote_events.py:_VOTE_VALUE_MAP`; "not voting" is the only one
# with a space, which the frontend slug-cases for class names.
_OPTION_LABELS = {
    'yes':         'Yes',
    'no':          'No',
    'abstain':     'Abstain',
    'absent':      'Absent',
    'excused':     'Excused',
    'not voting':  'Not voting',
    'other':       'Other',
}


def _get_voting_history(person_id: str) -> Dict[str, Any]:
    """Aggregate lifetime voting stats — the at-a-glance breakdown
    pill row above the legislation involvement table. Filters on
    `voter_id` (the OCD Person primary key) rather than `voter_name`
    so name collisions between former and current members can't leak
    across reps; the scraper sets `voter` whenever the name resolves
    to a Person we've scraped.

    Returns `{total, breakdown: {option: count, ...}}`; `breakdown`
    only contains options the rep has actually cast (zero entries
    dropped server-side). Pre-scrape historical members produce
    total=0 here."""
    if not person_id:
        return {'total': 0, 'breakdown': {}}

    breakdown_qs = (
        PersonVote.objects
        .filter(voter_id=person_id)
        .values('option')
        .annotate(n=Count('id'))
    )
    breakdown = {row['option']: row['n'] for row in breakdown_qs}
    return {'total': sum(breakdown.values()), 'breakdown': breakdown}


# Mirrors `_normalise_status` in seattle_app/api_views.py — same status
# label + variant pair the legislation index uses on its cards. Imported
# at call time so a circular `seattle_app -> reps -> seattle_app` import
# during module init can't form (reps loads early; seattle_app builds
# views that import from reps).
def _normalise_status_lazy(raw: str) -> tuple[str, str]:
    from seattle_app.api_views import _normalise_status
    return _normalise_status(raw)


# Bodies whose votes count as "council vote" rather than "committee
# vote". The scraper sets `event_body_name` from Legistar's
# `EventBodyName`; only the literal full-council body slots into the
# council column.
_COUNCIL_BODY = "City Council"


def _vote_dict(person_vote: 'PersonVote') -> Dict[str, Any]:
    ve = person_vote.vote_event
    return {
        'option':       person_vote.option,
        'option_label': _OPTION_LABELS.get(person_vote.option, person_vote.option.title()),
        'body_name':    (ve.extras or {}).get('event_body_name') or '',
        'date':         (ve.start_date or '')[:10],
        'result':       ve.result,
    }


def _get_legislation_involvement(person_id: str, name: str
                                 ) -> List[Dict[str, Any]]:
    """One row per bill where this rep has any involvement (sponsored
    OR voted). Frontend renders this as a searchable, paginated table;
    bills the rep neither sponsored nor voted on are excluded so the
    page stays scoped to their own legislative footprint.

    Vote events are bucketed by `event_body_name`: 'City Council' →
    `council_vote`, anything else → `committee_vote`. For the rare
    bills with multiple committee votes (budget bills, big zoning
    packages — see WORK_LOG distribution: 6 of 330 bills have 3+
    votes), the most-recent one fills `committee_vote` and
    `extra_committee_votes` carries the count of older ones, which
    the frontend renders as a "+N more" link to the bill detail page
    for the full roll-call.

    `outcome` is the result of the bill's most-recent VoteEvent (the
    council vote when present, else the committee vote). Differs from
    `status` (the bill's MatterStatusName lifecycle label): a bill
    can have a passing council vote but still sit in 'Awaiting Mayor's
    Signature' as its overall status.

    Sponsorship: 'primary' beats 'cosponsor' if the rep holds both
    roles on a bill (theoretically possible if the data has duplicate
    sponsorship rows; in practice we see one sponsorship per
    (bill, person)). Returns 'primary' / 'cosponsor' / None."""
    if not person_id or not name:
        return []

    # 1. Sponsorships keyed by bill_id. Sponsorship.name is case-sensitive
    #    in the DB but reps' names appear consistently — `iexact` mirrors
    #    the legislation index sponsor filter for safety.
    sponsorships_by_bill: Dict[str, str] = {}
    name_lower = name.lower()
    sponsorship_rows = (
        Bill.objects
        .filter(sponsorships__name__iexact=name)
        .prefetch_related('sponsorships')
    )
    for bill in sponsorship_rows:
        is_primary = any(
            s.primary and (s.entity_name or '').lower() == name_lower
            for s in bill.sponsorships.all()
        )
        sponsorships_by_bill[bill.id] = 'primary' if is_primary else 'cosponsor'

    # 2. Per-person votes joined to VoteEvent (for body name + result).
    #    Order ascending so the latest vote of each kind overwrites
    #    older ones in the bucket below — same lex-sort assumption as
    #    `_get_voting_history`: ISO-8601 with fixed-offset suffix sorts
    #    chronologically because the date prefix dominates.
    pv_qs = (
        PersonVote.objects
        .filter(voter_id=person_id)
        .select_related('vote_event')
        .order_by('vote_event__start_date')
    )

    votes_by_bill: Dict[str, Dict[str, Any]] = {}
    for pv in pv_qs:
        ve = pv.vote_event
        bill_id = ve.bill_id
        if not bill_id:
            continue
        body = ((ve.extras or {}).get('event_body_name') or '').strip()
        is_council = body == _COUNCIL_BODY
        bucket = votes_by_bill.setdefault(bill_id, {
            'committee_vote':         None,
            'council_vote':           None,
            'extra_committee_votes':  0,
            'outcome':                None,
        })
        v = _vote_dict(pv)
        if is_council:
            bucket['council_vote'] = v
        else:
            if bucket['committee_vote'] is not None:
                bucket['extra_committee_votes'] += 1
            bucket['committee_vote'] = v
        # Most-recent VoteEvent's result wins (qs is ordered ascending).
        bucket['outcome'] = ve.result

    # 3. Union of bill_ids and bulk-fetch metadata.
    all_bill_ids = set(sponsorships_by_bill) | set(votes_by_bill)
    if not all_bill_ids:
        return []

    bill_meta: Dict[str, Dict[str, Any]] = {}
    bills = (
        Bill.objects
        .filter(id__in=all_bill_ids)
        .annotate(latest_action_date=Max('actions__date'))
    )
    for b in bills:
        raw_status = (b.extras or {}).get('MatterStatusName', '')
        status_label, status_variant = _normalise_status_lazy(raw_status)
        bill_meta[b.id] = {
            'identifier':         b.identifier,
            'title':              b.title or '',
            'slug':               b.slug,
            'status_label':       status_label,
            'status_variant':     status_variant,
            'latest_action_date': b.latest_action_date,
        }

    # 4. Compose rows and sort by most-recent activity first.
    rows: List[Dict[str, Any]] = []
    for bill_id in all_bill_ids:
        meta = bill_meta.get(bill_id)
        if not meta:
            continue  # bill scrubbed since the join — skip cleanly
        votes = votes_by_bill.get(bill_id, {})
        rows.append({
            'bill': {
                'identifier': meta['identifier'],
                'title':      meta['title'],
                'slug':       meta['slug'],
            },
            'status': {
                'label':   meta['status_label'],
                'variant': meta['status_variant'],
            },
            'sponsorship':           sponsorships_by_bill.get(bill_id),
            'committee_vote':        votes.get('committee_vote'),
            'council_vote':          votes.get('council_vote'),
            'extra_committee_votes': votes.get('extra_committee_votes', 0),
            'outcome':               votes.get('outcome'),
            'latest_action_date':    meta['latest_action_date'],
        })
    rows.sort(key=lambda r: r['latest_action_date'] or '', reverse=True)
    return rows


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

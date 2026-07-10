"""Minimal OCD/councilmatic object graph for digest tests (#235).

First tests in the repo to build Bill/Event fixtures — the scrape pipeline
normally owns these tables. Everything funnels through ``get_or_create`` on
stable ids so helpers compose freely inside one test without collisions.
"""
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.db import connection
from django.utils.text import slugify

from councilmatic_core.models import Bill, Event
from opencivicdata.core.models import (
    Division, Jurisdiction, Membership, Organization, Person,
)
from opencivicdata.legislative.models import (
    BillAction, BillSponsorship, LegislativeSession,
)

from digests.models import Subscriber, SubscriberPreferences
from reps.models import District
from seattle_app.models import BillTags, EventSummary, LegislationSummary

COUNCIL_NAME = "Seattle City Council"


def jurisdiction():
    division, _ = Division.objects.get_or_create(
        id="ocd-division/country:us/state:wa/place:seattle",
        defaults={"name": "Seattle", "country": "us"},
    )
    juris, _ = Jurisdiction.objects.get_or_create(
        id="ocd-jurisdiction/country:us/state:wa/place:seattle/government",
        defaults={
            "name": "Seattle",
            "url": "https://seattle.gov",
            "division": division,
        },
    )
    return juris


def legislative_session():
    session, _ = LegislativeSession.objects.get_or_create(
        jurisdiction=jurisdiction(),
        identifier="2026",
        defaults={
            "name": "2026 Session",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
    )
    return session


def council():
    org, _ = Organization.objects.get_or_create(
        name=COUNCIL_NAME,
        defaults={"classification": "legislature", "jurisdiction": jurisdiction()},
    )
    return org


def committee(name):
    org, _ = Organization.objects.get_or_create(
        name=name,
        defaults={"classification": "committee", "jurisdiction": jurisdiction()},
    )
    return org


def _ensure_headshot_default():
    """Upstream django-councilmatic dropped ``headshot`` from its Person
    model, but our schema is pinned at councilmatic_core.0053 (see the
    comment in digests/0001), so the test DB still carries the column as
    NOT NULL. The library's post_save signal mirrors every new OCD Person
    into councilmatic_core_person through the ORM — which can't see the
    column — so give it a DB-level default. Static DDL, idempotent."""
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE councilmatic_core_person "
            "ALTER COLUMN headshot SET DEFAULT ''"
        )


def councilmember(name, seat_label):
    """Person + active council Membership (label like "District 3" or
    "Position 8" — the label is what the district dimension matches on)."""
    _ensure_headshot_default()
    person = Person.objects.create(name=name)
    Membership.objects.create(
        person=person,
        organization=council(),
        label=seat_label,
        role="Councilmember",
    )
    return person


def committee_membership(person, committee_org, role="Member"):
    return Membership.objects.create(
        person=person, organization=committee_org, role=role
    )


def bill(identifier, *, action_date, title=None, tags=None, sponsors=(),
         primary=True, summary=None):
    """A councilmatic Bill with one action on ``action_date`` (ISO string),
    optional BillTags, sponsorships, and LegislationSummary."""
    b = Bill.objects.create(
        legislative_session=legislative_session(),
        identifier=identifier,
        title=title or f"A bill about {identifier}",
        slug=slugify(identifier),
    )
    BillAction.objects.create(
        bill=b,
        organization=council(),
        description="Passed as amended",
        date=action_date,
        order=1,
    )
    if tags:
        BillTags.objects.create(bill=b, tags=tags)
    for person in sponsors:
        BillSponsorship.objects.create(
            bill=b,
            name=person.name,
            classification="sponsor",
            person=person,
            primary=primary,
        )
    if summary:
        LegislationSummary.objects.create(
            bill=b, summary=summary, model_version="test-model"
        )
    return b


def meeting(name, *, start_date, overview=None):
    """A councilmatic Event; pass ``overview`` to attach the EventSummary
    that makes it digest-eligible."""
    event = Event.objects.create(
        jurisdiction=jurisdiction(),
        name=name,
        description="",
        classification="committee-meeting",
        start_date=start_date,
        status="passed",
        slug=slugify(f"{name} {start_date}"),
    )
    if overview:
        EventSummary.objects.create(event=event, overview=overview)
    return event


def district(number="3"):
    square = Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)))
    d, _ = District.objects.get_or_create(
        number=number,
        defaults={
            "name": f"District {number}" if number != "At Large" else "Citywide At Large",
            "geometry": MultiPolygon(square),
        },
    )
    return d


def subscriber(email, *, status=Subscriber.STATUS_ACTIVE, weekly=True,
               daily=False, issue_areas=None, followed_reps=(),
               followed_bills=(), district_obj=None):
    sub = Subscriber.objects.create(email=email, status=status)
    prefs = SubscriberPreferences.objects.create(
        subscriber=sub,
        weekly_enabled=weekly,
        daily_enabled=daily,
        issue_areas=issue_areas or [],
        district=district_obj,
    )
    if followed_reps:
        prefs.followed_reps.set(followed_reps)
    if followed_bills:
        prefs.followed_bills.set(followed_bills)
    return sub

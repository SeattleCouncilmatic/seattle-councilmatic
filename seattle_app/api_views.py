"""
JSON API views for the React frontend homepage.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.db.models import Max
from councilmatic_core.models import Bill, Event
from django.shortcuts import get_object_or_404


# Status label mapping from Legistar's MatterStatusName values (case-insensitive keys)
_STATUS_LABELS = {
    # Final outcomes
    'passed':                       'Passed',
    'passed at full council':       'Passed',
    'adopted':                      'Adopted',
    'failed':                       'Failed',
    'did not pass':                 'Failed',
    'signed':                       'Signed',
    'vetoed':                       'Vetoed',
    'tabled':                       'Tabled',
    # Active / in-progress
    'in committee':                 'In Committee',
    'committee agenda ready':       'In Committee',
    'full council agenda ready':    'Full Council',
    'introduction & referral ready': 'Introduced',
    'introduced':                   'Introduced',
}

# CSS colour variant for each status (consumed by the frontend tag component)
_STATUS_VARIANTS = {
    'Passed':       'green',
    'Adopted':      'green',
    'Signed':       'green',
    'Failed':       'red',
    'Vetoed':       'red',
    'Tabled':       'gray',
    'In Committee': 'yellow',
    'Full Council': 'blue',
    'Introduced':   'blue',
}


def _normalise_status(raw: str) -> tuple[str, str]:
    """Return (display_label, variant) for a Legistar MatterStatusName string."""
    label = _STATUS_LABELS.get(raw.lower(), raw)
    variant = _STATUS_VARIANTS.get(label, 'gray')
    return label, variant


@require_GET
def recent_legislation(request):
    """
    GET /api/legislation/recent/

    Returns the 10 most-recently-actioned bills, ordered newest first.
    Uses last_action_date when available, falls back to the introduced
    action date stored in extras / actions.
    """
    limit = min(int(request.GET.get('limit', 10)), 50)

    bills = (
        Bill.objects
        .prefetch_related('actions', 'sponsorships')
        .annotate(latest_action_date=Max('actions__date'))
        .order_by('-latest_action_date')[:limit]
    )

    results = []
    for bill in bills:
        # Sponsor name from first sponsorship record
        sponsorship = bill.sponsorships.first()
        sponsor_name = sponsorship.entity_name if sponsorship else None

        # Introduced date: earliest action date for this bill
        earliest_action = bill.actions.order_by('date').first()
        intro_date = earliest_action.date[:10] if earliest_action and earliest_action.date else None

        raw_status = bill.extras.get('MatterStatusName', '')
        status_label, status_variant = _normalise_status(raw_status)

        results.append({
            'identifier':     bill.identifier,
            'title':          bill.title,
            'sponsor':        sponsor_name,
            'status':         status_label,
            'status_variant': status_variant,
            'date_introduced': intro_date,
            'slug':           bill.slug,
        })

    return JsonResponse({'results': results})


@require_GET
def upcoming_meetings(request):
    """
    GET /api/meetings/upcoming/

    Returns the next 10 upcoming confirmed or tentative council meetings,
    ordered soonest first.
    """
    limit = min(int(request.GET.get('limit', 10)), 50)
    now = timezone.now()

    events = (
        Event.objects
        .filter(start_date__gte=now)
        .exclude(status='cancelled')
        .order_by('start_date')[:limit]
    )

    results = []
    for event in events:
        results.append({
            'name':        event.name,
            'start_date':  event.start_date if isinstance(event.start_date, str) else event.start_date.isoformat(),
            'status':      event.status,
            'description': event.description or '',
            'slug':        event.slug,
        })

    return JsonResponse({'results': results})


@require_GET
def meeting_detail(request, slug):
    """
    GET /api/meetings/<slug>/

    Returns full detail for a single event: core fields, agenda/minutes
    document URLs, and a list of substantive agenda items with attachments
    and internal bill links where available.
    """
    event = get_object_or_404(
        Event.objects.prefetch_related(
            'sources',
            'agenda',
            'agenda__related_entities',
            'agenda__media__links',
        ),
        slug=slug,
    )

    start = event.start_date
    end   = event.end_date

    # Public-facing Legistar URL (stored as a source during scraping)
    source = event.sources.first()
    legistar_url = source.url if source else None

    # Build agenda items list, ordered by agenda sequence
    agenda_items = []
    for item in event.agenda.order_by('order'):
        # Resolve internal bill slug via related_entities
        bill_slug = None
        for rel in item.related_entities.all():
            if rel.entity_type == 'bill' and rel.entity_id:
                # entity_id is the OCD bill ID; look up the councilmatic slug
                bill = Bill.objects.filter(id=rel.entity_id).values_list('slug', flat=True).first()
                if bill:
                    bill_slug = bill
                    break

        # Collect attachments from media links
        attachments = []
        for media in item.media.all():
            for link in media.links.all():
                attachments.append({
                    'name':       media.note,
                    'url':        link.url,
                    'media_type': link.media_type,
                })

        agenda_items.append({
            'order':         item.order,
            'description':   item.description,
            'matter_file':   item.extras.get('matter_file'),
            'matter_type':   item.extras.get('matter_type'),
            'matter_status': item.extras.get('matter_status'),
            'passed_flag':   item.extras.get('passed_flag'),
            'action_text':   item.extras.get('action_text'),
            'bill_slug':     bill_slug,
            'attachments':   attachments,
        })

    return JsonResponse({
        'name':             event.name,
        'slug':             event.slug,
        'start_date':       start if isinstance(start, str) else start.isoformat() if start else None,
        'end_date':         (end if isinstance(end, str) else end.isoformat() if end else None) or None,
        'status':           event.status,
        'location':         str(event.location).strip() if event.location else None,
        'description':      event.description or '',
        'legistar_url':     legistar_url,
        'agenda_file_url':  event.extras.get('agenda_file_url'),
        'agenda_status':    event.extras.get('agenda_status'),
        'packet_url':       event.extras.get('packet_url'),
        'minutes_file_url': event.extras.get('minutes_file_url'),
        'minutes_status':   event.extras.get('minutes_status'),
        'agenda_items':     agenda_items,
    })


@require_GET
def legislation_detail(request, slug):
    """
    GET /api/legislation/<slug>/

    Returns full detail for a single bill: core fields, sponsor list,
    full action history (oldest first), and attached documents.
    """
    bill = get_object_or_404(
        Bill.objects.prefetch_related('actions', 'sponsorships', 'documents__links'),
        slug=slug,
    )

    raw_status = bill.extras.get('MatterStatusName', '')
    status_label, status_variant = _normalise_status(raw_status)

    # Sponsors ordered by primary first
    sponsors = [
        {
            'name':    s.entity_name,
            'primary': s.primary,
        }
        for s in bill.sponsorships.order_by('-primary', 'name')
    ]

    # Full action history, oldest first, deduplicating same-date/same-description pairs
    seen_actions = set()
    actions = []
    for a in bill.actions.order_by('date', 'description'):
        key = (a.date[:10] if a.date else '', a.description)
        if key in seen_actions:
            continue
        seen_actions.add(key)
        actions.append({
            'date':        a.date[:10] if a.date else None,
            'description': a.description,
        })

    # Attached documents with download links
    documents = []
    for doc in bill.documents.all():
        for link in doc.links.all():
            documents.append({
                'name': doc.note,
                'url':  link.url,
                'media_type': link.media_type,
            })

    # Earliest action date as introduced date
    earliest = bill.actions.order_by('date').first()
    date_introduced = earliest.date[:10] if earliest and earliest.date else None

    return JsonResponse({
        'identifier':      bill.identifier,
        'title':           bill.title,
        'classification':  bill.classification,
        'status':          status_label,
        'status_variant':  status_variant,
        'committee':       bill.extras.get('MatterBodyName', ''),
        'bill_type':       bill.extras.get('MatterTypeName', ''),
        'last_modified':   bill.extras.get('MatterLastModifiedUtc', ''),
        'date_introduced': date_introduced,
        'legistar_id':     bill.extras.get('MatterId'),
        'sponsors':        sponsors,
        'actions':         actions,
        'documents':       documents,
        'slug':            bill.slug,
    })

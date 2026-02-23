"""
JSON API views for the React frontend homepage.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.db.models import Max
from councilmatic_core.models import Bill, Event


# Status label mapping from Legistar's MatterStatusName values
_STATUS_LABELS = {
    'in committee': 'In Committee',
    'passed':       'Passed',
    'failed':       'Failed',
    'signed':       'Signed',
    'vetoed':       'Vetoed',
    'introduced':   'Introduced',
    'tabled':       'Tabled',
}

# CSS colour variant for each status (consumed by the frontend tag component)
_STATUS_VARIANTS = {
    'In Committee': 'yellow',
    'Passed':       'green',
    'Signed':       'green',
    'Failed':       'red',
    'Vetoed':       'red',
    'Introduced':   'blue',
    'Tabled':       'gray',
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

        # Introduced date from the first action labelled "Introduced"
        intro_action = bill.actions.filter(description__iexact='Introduced').first()
        intro_date = (
            intro_action.date[:10]          # ISO date string → YYYY-MM-DD
            if intro_action and intro_action.date
            else None
        )

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

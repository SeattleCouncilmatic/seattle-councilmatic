"""
JSON API views for the React frontend homepage.
"""

import html
import re
from functools import reduce
from operator import or_

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import Count, Max, Min, Q
from councilmatic_core.models import Bill, Event
from django.shortcuts import get_object_or_404

from .models import CodeChapter, CodeTitle, MunicipalCodeSection, Subchapter, TitleAppendix


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


# Status filter values exposed to the frontend (the normalized labels from
# _STATUS_VARIANTS, in display order). Anything not in this list is rejected
# server-side so a typo doesn't silently return zero results.
_STATUS_FILTER_VALUES = ['Passed', 'Adopted', 'Signed', 'Failed', 'Vetoed',
                         'Tabled', 'In Committee', 'Full Council', 'Introduced']

# Sort options. `recent` is the default and matches the previous
# (un-parametrized) behavior — bills with the most recent action surface
# first. `introduced` orders by the earliest action date (i.e. when a
# bill first hit the docket) so the sort surfaces newly-filed work
# regardless of subsequent activity. `identifier` is alphabetical for
# users who know the citation they're after.
_SORT_VALUES = {
    'recent':     ('-latest_action_date', 'Most recent activity'),
    'introduced': ('-earliest_action_date', 'Most recently introduced'),
    'identifier': ('identifier',           'Identifier (CB number)'),
}
_DEFAULT_SORT = 'recent'


def _safe_int(raw, default, max_value=None):
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < 0:
        return default
    if max_value is not None and v > max_value:
        return max_value
    return v


@require_GET
def legislation_index(request):
    """
    GET /api/legislation/?q=<text>&status=<label>&sort=<key>&limit=20&offset=0

    Search and filter all legislation; paginated. `sort` is one of
    _SORT_VALUES (defaults to `recent` — the previous behavior). `status`
    is one of the normalized labels from _STATUS_VARIANTS (case-
    sensitive); the filter expands to all raw `MatterStatusName` values
    that map to that label.
    """
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    sort = request.GET.get('sort', '').strip() or _DEFAULT_SORT
    if sort not in _SORT_VALUES:
        sort = _DEFAULT_SORT
    limit = _safe_int(request.GET.get('limit'), default=20, max_value=100)
    offset = _safe_int(request.GET.get('offset'), default=0)

    bills = Bill.objects.all()

    if q:
        bills = bills.filter(Q(identifier__icontains=q) | Q(title__icontains=q))

    if status_filter:
        if status_filter not in _STATUS_FILTER_VALUES:
            bills = bills.none()
        else:
            raw_matches = [raw for raw, label in _STATUS_LABELS.items()
                           if label == status_filter]
            if raw_matches:
                status_q = reduce(or_, (Q(extras__MatterStatusName__iexact=v)
                                        for v in raw_matches))
                bills = bills.filter(status_q)
            else:
                bills = bills.none()

    total_count = bills.count()

    sort_field, _sort_label = _SORT_VALUES[sort]
    bills = (
        bills
        .prefetch_related('actions', 'sponsorships')
        .annotate(
            latest_action_date=Max('actions__date'),
            earliest_action_date=Min('actions__date'),
        )
        .order_by(sort_field)[offset:offset + limit]
    )

    results = []
    for bill in bills:
        sponsorship = bill.sponsorships.first()
        sponsor_name = sponsorship.entity_name if sponsorship else None

        earliest_action = bill.actions.order_by('date').first()
        intro_date = earliest_action.date[:10] if earliest_action and earliest_action.date else None

        raw_status = bill.extras.get('MatterStatusName', '')
        status_label, status_variant = _normalise_status(raw_status)

        results.append({
            'identifier':        bill.identifier,
            'title':             bill.title,
            'title_highlighted': _highlight_substring(bill.title, q) if q else None,
            'sponsor':           sponsor_name,
            'status':            status_label,
            'status_variant':    status_variant,
            'date_introduced':   intro_date,
            'slug':              bill.slug,
        })

    return JsonResponse({
        'results':       results,
        'total_count':   total_count,
        'limit':         limit,
        'offset':        offset,
        'sort':          sort,
        'status_values': _STATUS_FILTER_VALUES,
        'sort_values':   [{'value': k, 'label': v[1]} for k, v in _SORT_VALUES.items()],
    })


_TIME_FILTER_VALUES = ['upcoming', 'past', 'all']
_TYPE_FILTER_VALUES = ['Council', 'Briefing', 'Committee', 'Hearing', 'Other']


def _classify_event(name: str) -> str:
    """Bucket a Legistar event into one of _TYPE_FILTER_VALUES based on its
    name. The Legistar API doesn't expose a structured "event type" — type
    is implicit in `EventBodyName` — so we derive it. `Committee` is the
    fallback for anything name-shaped because some committees come back
    truncated (e.g. `'Transportation and Seattle Public Utilities'` lacks
    the trailing word "Committee" in the Legistar source data); reserving
    `Other` for clearly-non-meeting entries like quorum notices keeps the
    chip useful instead of noisy.
    """
    n = (name or '').lower().strip()
    if not n:
        return 'Other'
    if 'public hearing' in n:
        return 'Hearing'
    if 'briefing' in n:
        return 'Briefing'
    if n.startswith('city council'):
        return 'Council'
    if n.startswith('notice'):
        return 'Other'
    return 'Committee'


def _serialize_event(event) -> dict:
    """Shape used by /api/events/ and /api/events/upcoming/. Includes the
    document URLs and the agenda_status so the frontend card can surface
    cancellations and let users open Agenda/Packet/Minutes without
    clicking through to the detail page. `legistar_url` requires
    `sources` to be prefetched on the queryset."""
    source = event.sources.first()
    return {
        'name':             event.name,
        'type':             _classify_event(event.name),
        'start_date':       event.start_date if isinstance(event.start_date, str) else event.start_date.isoformat(),
        'status':           event.status,
        'description':      event.description or '',
        'slug':             event.slug,
        'agenda_file_url':  event.extras.get('agenda_file_url'),
        'agenda_status':    event.extras.get('agenda_status'),
        'packet_url':       event.extras.get('packet_url'),
        'minutes_file_url': event.extras.get('minutes_file_url'),
        'minutes_status':   event.extras.get('minutes_status'),
        'legistar_url':     source.url if source else None,
    }


@require_GET
def events_index(request):
    """
    GET /api/events/?q=<text>&time=<upcoming|past|all>&type=<label>&limit=20&offset=0

    Search and browse all events; paginated. The `time` param controls
    both the slice of events returned and the sort direction:
      - upcoming (default) — start_date >= now, sorted soonest first
      - past                — start_date <  now, sorted most-recent first
      - all                 — every event, sorted most-recent first
    `type` is one of _TYPE_FILTER_VALUES; filtering by type happens
    in-Python after the queryset slice because event type is derived
    from the name rather than stored as a column.
    """
    q = request.GET.get('q', '').strip()
    time_filter = request.GET.get('time', 'upcoming').strip().lower()
    type_filter = request.GET.get('type', '').strip()
    limit = _safe_int(request.GET.get('limit'), default=20, max_value=100)
    offset = _safe_int(request.GET.get('offset'), default=0)

    if time_filter not in _TIME_FILTER_VALUES:
        time_filter = 'upcoming'
    if type_filter and type_filter not in _TYPE_FILTER_VALUES:
        # Reject unknown types rather than silently ignore.
        return JsonResponse({
            'results': [], 'total_count': 0,
            'limit': limit, 'offset': offset,
            'time_values': _TIME_FILTER_VALUES,
            'type_values': _TYPE_FILTER_VALUES,
        })

    events = Event.objects.prefetch_related('sources')

    if q:
        events = events.filter(name__icontains=q)

    now = timezone.now()
    if time_filter == 'upcoming':
        events = events.filter(start_date__gte=now).order_by('start_date')
    elif time_filter == 'past':
        events = events.filter(start_date__lt=now).order_by('-start_date')
    else:
        events = events.order_by('-start_date')

    if type_filter:
        # Type is derived from name; expand to the names that classify to
        # the requested type so we can filter at the DB layer.
        all_names = list(events.values_list('name', flat=True).distinct())
        matching_names = [n for n in all_names if _classify_event(n) == type_filter]
        if not matching_names:
            events = events.none()
        else:
            events = events.filter(name__in=matching_names)

    total_count = events.count()
    events = events[offset:offset + limit]

    results = [_serialize_event(e) for e in events]

    return JsonResponse({
        'results':     results,
        'total_count': total_count,
        'limit':       limit,
        'offset':      offset,
        'time_values': _TIME_FILTER_VALUES,
        'type_values': _TYPE_FILTER_VALUES,
    })


@require_GET
def upcoming_events(request):
    """
    GET /api/events/upcoming/

    Returns the next 10 upcoming confirmed or tentative events,
    ordered soonest first.
    """
    limit = min(int(request.GET.get('limit', 10)), 50)
    now = timezone.now()

    events = (
        Event.objects
        .prefetch_related('sources')
        .filter(start_date__gte=now)
        .exclude(status='cancelled')
        .order_by('start_date')[:limit]
    )

    return JsonResponse({'results': [_serialize_event(e) for e in events]})


@require_GET
def event_detail(request, slug):
    """
    GET /api/events/<slug>/

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


# ---------------------------------------------------------------------------
# Seattle Municipal Code (SMC) endpoints
# ---------------------------------------------------------------------------

# Section numbers look like "23.47A.004", chapter numbers like "23.47A",
# title numbers like "23" or "12A". Anything matching this regex is treated
# as a citation prefix and routed through trigram/btree on section_number
# rather than the FTS path.
_CITATION_RE = re.compile(r'^[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+){0,2}$')


def _appendix_label_to_slug(label: str) -> str:
    """'I AND II' -> 'i-and-ii'. Lossy in theory but the label set is tiny
    (Title 15 only, today) and characters outside [A-Za-z0-9 ] don't appear."""
    return re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')


def _title_sort_key(title_number: str) -> tuple[int, str]:
    """Sort titles by numeric prefix so '10' lands after '2', not after '1'.
    '12A' compares right because the numeric prefix tuple ties first."""
    m = re.match(r'^(\d+)', title_number)
    return (int(m.group(1)) if m else 0, title_number)


def _section_path_parts(section_number: str) -> tuple[str, str, str] | None:
    """'23.47A.004' -> ('23', '47A', '004'). None if shape is wrong."""
    parts = section_number.split('.')
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def _section_sort_key(section_number: str) -> tuple:
    """Document-order sort key for section_number. Each dotted component
    splits into (numeric_prefix, suffix), which makes 9 < 9A < 10 (numeric
    prefix 9 == 9 ties on first part; '' < 'A' on second) and 1.x < 2.x <
    10.x (the title-level int beats lex ordering where '.'<'0' would
    otherwise jump from 1 to 10 before 2)."""
    parts = section_number.split('.')
    out = []
    for p in parts:
        m = re.match(r'^(\d*)(.*)$', p)
        num_str = m.group(1)
        suffix = m.group(2)
        out.append((int(num_str) if num_str else 0, suffix))
    return tuple(out)


# Cache the sorted section list so prev/next doesn't re-fetch + re-sort
# 7k rows on every detail request. The mtime invalidator picks up the
# parser's most recent run; new sections will appear after the next
# parse cycle. Tradeoff: a few seconds of staleness is fine for a code
# of laws that updates monthly.
_SECTION_NEIGHBORS_CACHE = {'mtime': None, 'sorted': None}


def _get_sorted_sections() -> list[tuple[str, str]]:
    """Returns [(section_number, title), ...] in document order. Cached
    until the latest MunicipalCodeSection.last_updated changes."""
    latest = MunicipalCodeSection.objects.aggregate(Max('last_updated'))['last_updated__max']
    if _SECTION_NEIGHBORS_CACHE['mtime'] == latest and _SECTION_NEIGHBORS_CACHE['sorted'] is not None:
        return _SECTION_NEIGHBORS_CACHE['sorted']
    rows = list(MunicipalCodeSection.objects
                .order_by()
                .values_list('section_number', 'title'))
    rows.sort(key=lambda r: _section_sort_key(r[0]))
    _SECTION_NEIGHBORS_CACHE['mtime'] = latest
    _SECTION_NEIGHBORS_CACHE['sorted'] = rows
    return rows


def _section_neighbors_pair(section_number: str) -> dict:
    """Returns {'prev': ..., 'next': ...} for a section by document-order
    position. Cross-title lex on raw section_number doesn't work because
    '.' (46) < '0' (48) makes '1.99.999' < '10.01.010' byte-wise, so SQL
    ordering would jump from title 1 directly to title 10 instead of
    going to title 2. Sort happens in Python on a cached list."""
    rows = _get_sorted_sections()
    idx = next((i for i, r in enumerate(rows) if r[0] == section_number), None)
    if idx is None:
        return {'prev': None, 'next': None}

    def _make(target_idx: int) -> dict | None:
        if target_idx < 0 or target_idx >= len(rows):
            return None
        sn, t = rows[target_idx]
        parts = _section_path_parts(sn)
        return {
            'primary':   sn,
            'secondary': t,
            'path':      f'/municode/{parts[0]}/{parts[1]}/{parts[2]}' if parts else None,
        }

    return {'prev': _make(idx - 1), 'next': _make(idx + 1)}


def _chapter_neighbor(direction: str, chapter_number: str, title_number: str) -> dict | None:
    """Previous/next chapter within the same title. Lex on chapter_number
    works because every chapter within a title shares the same title prefix
    and chapter-number differences land before any letter suffix."""
    qs = MunicipalCodeSection.objects.filter(title_number=title_number)
    if direction == 'prev':
        n = (qs.filter(chapter_number__lt=chapter_number)
               .values_list('chapter_number', flat=True)
               .order_by('-chapter_number').first())
    else:
        n = (qs.filter(chapter_number__gt=chapter_number)
               .values_list('chapter_number', flat=True)
               .order_by('chapter_number').first())
    if not n:
        return None
    short = '.'.join(n.split('.')[1:])
    name = CodeChapter.objects.filter(chapter_number=n).values_list('name', flat=True).first()
    return {
        'primary':   f'Chapter {n}',
        'secondary': name,
        'path':      f'/municode/{title_number}/{short}',
    }


def _title_neighbor(direction: str, title_number: str) -> dict | None:
    """Previous/next title in numeric-prefix order. Can't lex-compare in
    SQL because '10' < '2' bytewise, so we pull the distinct title list
    and sort in Python."""
    # Explicit .order_by('title_number') overrides the model's default Meta
    # ordering (which appends chapter_number + section_number to the SQL
    # ORDER BY, defeating DISTINCT and returning all 7k rows instead of
    # ~22 distinct titles). Python re-sort below applies the numeric-prefix
    # rule the SQL collation can't.
    titles = list(MunicipalCodeSection.objects
                  .order_by('title_number')
                  .values_list('title_number', flat=True)
                  .distinct())
    titles.sort(key=_title_sort_key)
    try:
        idx = titles.index(title_number)
    except ValueError:
        return None
    target_idx = idx - 1 if direction == 'prev' else idx + 1
    if target_idx < 0 or target_idx >= len(titles):
        return None
    n = titles[target_idx]
    name = CodeTitle.objects.filter(title_number=n).values_list('name', flat=True).first()
    return {
        'primary':   f'Title {n}',
        'secondary': name,
        'path':      f'/municode/{n}',
    }


def _highlight_substring(text: str | None, q: str) -> str | None:
    """Case-insensitively wrap occurrences of `q` within `text` in <mark>
    tags. HTML-escapes the text first so any tag-shaped content renders
    as text on the frontend; only the <mark> tags we insert are live.
    Used for legislation title highlighting since Bill search is plain
    icontains over identifier+title — no FTS to apply ts_headline to,
    but titles are often long enough that an inline highlight helps."""
    if not text:
        return None
    if not q:
        return html.escape(text)
    escaped_text = html.escape(text)
    escaped_q = html.escape(q)
    pattern = re.compile(re.escape(escaped_q), re.IGNORECASE)
    return pattern.sub(lambda m: f'<mark>{m.group(0)}</mark>', escaped_text)


def _safe_snippet(raw: str | None) -> str | None:
    """Sanitize a ts_headline result for safe rendering on the frontend.
    The full_text comes out of the PDF parser as plain text (no HTML),
    but we belt-and-suspender it: HTML-escape the whole snippet, then
    restore the <mark>/</mark> sentinels we asked Postgres to insert.
    Any other tag-shaped content in the source gets rendered as text.
    Also collapses the parser's hard line breaks so the snippet reads
    as flowing prose."""
    if not raw:
        return None
    escaped = html.escape(raw)
    snippet = (escaped
               .replace('&lt;mark&gt;', '<mark>')
               .replace('&lt;/mark&gt;', '</mark>'))
    return ' '.join(snippet.split())


def _serialize_section_card(s: MunicipalCodeSection, snippet: str | None = None) -> dict:
    """Compact shape for search results and chapter listings."""
    sub = s.subchapter
    return {
        'section_number':    s.section_number,
        'title':              s.title,
        'title_number':       s.title_number,
        'chapter_number':     s.chapter_number,
        'subchapter_roman':   sub.roman if sub else None,
        'subchapter_name':    sub.name if sub else None,
        'has_summary':        bool(s.plain_summary),
        'snippet':            snippet,
    }


@require_GET
def smc_search(request):
    """
    GET /api/smc/?q=<text>&title=<n>&chapter=<n>&limit=20&offset=0

    Searches MunicipalCodeSection. If `q` looks like a section/chapter/title
    citation prefix (e.g. "23.47A"), prefix-matches on section_number
    backed by the pg_trgm GIN index. Otherwise runs FTS against the
    pre-computed `search_vector` (weighted A/B/C over section_number,
    title, full_text) ordered by SearchRank.

    The optional `title` and `chapter` params narrow results to a single
    title or chapter — primarily for in-chapter search from the chapter
    page.
    """
    q = request.GET.get('q', '').strip()
    title_filter = request.GET.get('title', '').strip()
    chapter_filter = request.GET.get('chapter', '').strip()
    limit = _safe_int(request.GET.get('limit'), default=20, max_value=100)
    offset = _safe_int(request.GET.get('offset'), default=0)

    sections = MunicipalCodeSection.objects.select_related('subchapter')

    if title_filter:
        sections = sections.filter(title_number=title_filter)
    if chapter_filter:
        sections = sections.filter(chapter_number=chapter_filter)

    is_citation = bool(q) and _CITATION_RE.match(q) is not None

    if not q:
        # Browse-style listing inside a title/chapter filter — no search.
        sections = sections.order_by('section_number')
    elif is_citation:
        # Citation prefix lookup. Trigram GIN index handles ILIKE 'q%'.
        sections = sections.filter(section_number__istartswith=q).order_by('section_number')
    else:
        # FTS path. websearch_to_tsquery handles quoted phrases and OR/-
        # operators the way users expect from search engines.
        # SearchHeadline runs ts_headline on full_text — bounded cost
        # because we only annotate the post-LIMIT slice (see below).
        query = SearchQuery(q, search_type='websearch')
        sections = (sections
                    .filter(search_vector=query)
                    .annotate(
                        rank=SearchRank('search_vector', query),
                        snippet_raw=SearchHeadline(
                            'full_text', query,
                            start_sel='<mark>',
                            stop_sel='</mark>',
                            max_words=30,
                            min_words=15,
                            short_word=3,
                            highlight_all=False,
                        ),
                    )
                    .order_by('-rank', 'section_number'))

    total_count = sections.count()
    sections = sections[offset:offset + limit]

    results = [
        _serialize_section_card(s, snippet=_safe_snippet(getattr(s, 'snippet_raw', None)))
        for s in sections
    ]

    return JsonResponse({
        'results':     results,
        'total_count': total_count,
        'limit':       limit,
        'offset':      offset,
        'q':           q,
        'mode':        'citation' if is_citation else ('fts' if q else 'browse'),
    })


@require_GET
def smc_tree(request):
    """
    GET /api/smc/tree/

    Browse-tree skeleton: every title with its chapters and section
    counts, plus the appendix list. Sections aren't included — they're
    too numerous (7k+) and the chapter page fetches them on demand.
    """
    # Chapter section counts grouped by (title_number, chapter_number)
    chapter_rows = (
        MunicipalCodeSection.objects
        .values('title_number', 'chapter_number')
        .annotate(section_count=Count('id'))
        .order_by('title_number', 'chapter_number')
    )

    title_names = dict(CodeTitle.objects.values_list('title_number', 'name'))
    chapter_names = dict(CodeChapter.objects.values_list('chapter_number', 'name'))

    titles = {}
    for row in chapter_rows:
        tn = row['title_number']
        if tn not in titles:
            titles[tn] = {
                'title_number': tn,
                'name':         title_names.get(tn),
                'chapters':     [],
            }
        titles[tn]['chapters'].append({
            'chapter_number': row['chapter_number'],
            'name':           chapter_names.get(row['chapter_number']),
            'section_count':  row['section_count'],
        })

    title_list = sorted(titles.values(), key=lambda t: _title_sort_key(t['title_number']))

    appendices = [
        {
            'title_number': a.title_number,
            'label':        a.label,
            'label_slug':   _appendix_label_to_slug(a.label),
        }
        for a in TitleAppendix.objects.order_by('title_number', 'label')
    ]

    pdf_path = getattr(settings, 'SMC_PDF_PATH', None)
    source_pdf = None
    if pdf_path and pdf_path.exists():
        source_pdf = {
            'url':        '/smc.pdf',
            'filename':   pdf_path.name,
            'size_bytes': pdf_path.stat().st_size,
        }

    return JsonResponse({'titles': title_list, 'appendices': appendices, 'source_pdf': source_pdf})


@require_GET
def smc_title_detail(request, title_number):
    """
    GET /api/smc/titles/<title_number>/

    Single title: list of chapters with section counts. 404s when no
    section in the parsed PDF carries this title number.
    """
    chapters = (
        MunicipalCodeSection.objects
        .filter(title_number=title_number)
        .values('chapter_number')
        .annotate(section_count=Count('id'))
        .order_by('chapter_number')
    )
    chapter_names = dict(CodeChapter.objects.values_list('chapter_number', 'name'))
    chapter_list = [
        {
            'chapter_number': c['chapter_number'],
            'name':           chapter_names.get(c['chapter_number']),
            'section_count':  c['section_count'],
        }
        for c in chapters
    ]
    if not chapter_list:
        return JsonResponse({'error': 'Title not found'}, status=404)

    appendices = [
        {'label': a.label, 'label_slug': _appendix_label_to_slug(a.label)}
        for a in TitleAppendix.objects.filter(title_number=title_number).order_by('label')
    ]

    title_name = CodeTitle.objects.filter(title_number=title_number).values_list('name', flat=True).first()

    return JsonResponse({
        'title_number': title_number,
        'name':         title_name,
        'chapters':     chapter_list,
        'appendices':   appendices,
        'neighbors': {
            'prev': _title_neighbor('prev', title_number),
            'next': _title_neighbor('next', title_number),
        },
    })


@require_GET
def smc_chapter_detail(request, chapter_number):
    """
    GET /api/smc/chapters/<chapter_number>/

    Single chapter: sections grouped by subchapter, in document order.
    Sections without a subchapter appear in a leading "ungrouped" group.
    Subchapters with no sections in this run still appear (with empty
    section list) so the chapter TOC reflects the PDF structure.
    """
    sections = (
        MunicipalCodeSection.objects
        .filter(chapter_number=chapter_number)
        .select_related('subchapter')
        .order_by('section_number')
    )
    if not sections.exists():
        return JsonResponse({'error': 'Chapter not found'}, status=404)

    title_number = sections.first().title_number

    # All subchapters declared for this chapter — we list them even if
    # empty, so the user sees the official structure.
    subchapters_qs = Subchapter.objects.filter(chapter_number=chapter_number).order_by('ordinal')
    subchapter_index = {sc.id: sc for sc in subchapters_qs}

    # Build groups: ungrouped first, then each declared subchapter in
    # ordinal order. Sections fall into their FK group regardless of
    # arrival order in the queryset.
    ungrouped_sections = []
    grouped_sections = {sc_id: [] for sc_id in subchapter_index}
    for s in sections:
        card = {'section_number': s.section_number, 'title': s.title,
                'has_summary': bool(s.plain_summary)}
        if s.subchapter_id and s.subchapter_id in grouped_sections:
            grouped_sections[s.subchapter_id].append(card)
        else:
            ungrouped_sections.append(card)

    groups = []
    if ungrouped_sections:
        groups.append({'subchapter': None, 'sections': ungrouped_sections})
    for sc in subchapters_qs:
        groups.append({
            'subchapter': {'roman': sc.roman, 'name': sc.name},
            'sections':   grouped_sections[sc.id],
        })

    title_name = CodeTitle.objects.filter(title_number=title_number).values_list('name', flat=True).first()
    chapter_name = CodeChapter.objects.filter(chapter_number=chapter_number).values_list('name', flat=True).first()

    return JsonResponse({
        'title_number':   title_number,
        'title_name':     title_name,
        'chapter_number': chapter_number,
        'chapter_name':   chapter_name,
        'groups':         groups,
        'neighbors': {
            'prev': _chapter_neighbor('prev', chapter_number, title_number),
            'next': _chapter_neighbor('next', chapter_number, title_number),
        },
    })


@require_GET
def smc_section_detail(request, section_number):
    """
    GET /api/smc/sections/<section_number>/

    Full section: identifier, title, full_text, subchapter info, and
    LLM summary fields (placeholder until the summarize_smc_sections
    command lands).
    """
    s = get_object_or_404(
        MunicipalCodeSection.objects.select_related('subchapter'),
        section_number=section_number,
    )
    sub = s.subchapter
    title_name = CodeTitle.objects.filter(title_number=s.title_number).values_list('name', flat=True).first()
    chapter_name = CodeChapter.objects.filter(chapter_number=s.chapter_number).values_list('name', flat=True).first()
    return JsonResponse({
        'section_number':       s.section_number,
        'title':                s.title,
        'title_number':         s.title_number,
        'title_name':           title_name,
        'chapter_number':       s.chapter_number,
        'chapter_name':         chapter_name,
        'subchapter_roman':     sub.roman if sub else None,
        'subchapter_name':      sub.name if sub else None,
        'full_text':            s.full_text,
        'plain_summary':        s.plain_summary or None,
        'summary_model':        s.summary_model or None,
        'summary_generated_at': s.summary_generated_at.isoformat() if s.summary_generated_at else None,
        'source_pdf_page':      s.source_pdf_page,
        'neighbors':            _section_neighbors_pair(s.section_number),
    })


@require_GET
def smc_appendix_detail(request, title_number, label_slug):
    """
    GET /api/smc/appendices/<title_number>/<label_slug>/

    Appendix detail. Only Title 15 has appendices in the SMC today.
    The slug is the lowercased/dashed label ('i-and-ii') because the
    raw label contains spaces.
    """
    matches = [
        a for a in TitleAppendix.objects.filter(title_number=title_number)
        if _appendix_label_to_slug(a.label) == label_slug
    ]
    if not matches:
        return JsonResponse({'error': 'Appendix not found'}, status=404)
    a = matches[0]
    return JsonResponse({
        'title_number':    a.title_number,
        'label':           a.label,
        'full_text':       a.full_text,
        'source_pdf_page': a.source_pdf_page,
    })

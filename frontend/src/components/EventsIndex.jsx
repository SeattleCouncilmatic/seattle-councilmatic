import { useEffect, useState, useRef } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import EventCard from './EventCard'
import './EventsIndex.css'

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 300

const TIME_LABELS = {
  upcoming: 'Upcoming',
  past:     'Past',
  all:      'All',
}

export default function EventsIndex() {
  const [searchParams, setSearchParams] = useSearchParams()

  const q = searchParams.get('q') ?? ''
  const time = searchParams.get('time') ?? 'upcoming'
  const type = searchParams.get('type') ?? ''
  const committee = searchParams.get('committee') ?? ''
  const dateAfter = searchParams.get('date_after') ?? ''
  const dateBefore = searchParams.get('date_before') ?? ''
  const offset = Number(searchParams.get('offset') ?? 0)

  const [results, setResults] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [timeValues, setTimeValues] = useState(['upcoming', 'past', 'all'])
  const [typeValues, setTypeValues] = useState([])
  const [committeeValues, setCommitteeValues] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [searchInput, setSearchInput] = useState(q)
  const debounceTimer = useRef(null)

  useEffect(() => { setSearchInput(q) }, [q])

  useEffect(() => {
    if (searchInput === q) return
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      if (searchInput) next.set('q', searchInput)
      else next.delete('q')
      next.delete('offset')
      setSearchParams(next, { replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  useEffect(() => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (time && time !== 'upcoming') params.set('time', time)
    if (type) params.set('type', type)
    if (committee) params.set('committee', committee)
    if (dateAfter) params.set('date_after', dateAfter)
    if (dateBefore) params.set('date_before', dateBefore)
    params.set('limit', PAGE_SIZE)
    params.set('offset', offset)

    fetch(`/api/events/?${params.toString()}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => {
        setResults(data.results || [])
        setTotalCount(data.total_count ?? 0)
        if (data.time_values) setTimeValues(data.time_values)
        if (data.type_values) setTypeValues(data.type_values)
        if (data.committee_values) setCommitteeValues(data.committee_values)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [q, time, type, committee, dateAfter, dateBefore, offset])

  const handleTypeChange = (e) => {
    const next = new URLSearchParams(searchParams)
    if (e.target.value) next.set('type', e.target.value)
    else next.delete('type')
    next.delete('offset')
    setSearchParams(next)
  }

  const handleCommitteeChange = (e) => {
    const next = new URLSearchParams(searchParams)
    if (e.target.value) next.set('committee', e.target.value)
    else next.delete('committee')
    next.delete('offset')
    setSearchParams(next)
  }

  const handleDateChange = (paramName) => (e) => {
    const next = new URLSearchParams(searchParams)
    if (e.target.value) next.set(paramName, e.target.value)
    else next.delete(paramName)
    next.delete('offset')
    setSearchParams(next)
  }

  const handleTimeChange = (newTime) => {
    const next = new URLSearchParams(searchParams)
    if (newTime && newTime !== 'upcoming') next.set('time', newTime)
    else next.delete('time')
    next.delete('offset')
    setSearchParams(next)
  }

  const goToOffset = (newOffset) => {
    const next = new URLSearchParams(searchParams)
    if (newOffset > 0) next.set('offset', newOffset)
    else next.delete('offset')
    setSearchParams(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < totalCount

  return (
    <div className="evt-index-page">
      <div className="evt-index-container">
        <nav className="evt-index-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="evt-index-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="evt-index-breadcrumb-current">Events</span>
        </nav>
        <header className="evt-index-header">
          <h1 className="evt-index-title">Events</h1>
          <p className="evt-index-subtitle">
            Search and browse Seattle City Council events — full council meetings, committees, briefings, and hearings.
          </p>
        </header>

        <div className="evt-index-controls">
          <input
            type="search"
            className="evt-index-search"
            placeholder="Search by committee or event name…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search events"
            autoFocus
          />
          <select
            className="evt-index-type"
            value={type}
            onChange={handleTypeChange}
            aria-label="Filter by event type"
          >
            <option value="">All types</option>
            {typeValues.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <select
            className="evt-index-type"
            value={committee}
            onChange={handleCommitteeChange}
            aria-label="Filter by committee"
          >
            <option value="">All committees</option>
            {committeeValues.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <div className="evt-index-time-toggle" role="group" aria-label="Filter by time">
            {timeValues.map(v => (
              <button
                key={v}
                type="button"
                className={`evt-index-time-btn${time === v ? ' evt-index-time-btn--active' : ''}`}
                onClick={() => handleTimeChange(v)}
                aria-pressed={time === v}
              >
                {TIME_LABELS[v] ?? v}
              </button>
            ))}
          </div>
        </div>

        <div className="evt-index-controls evt-index-date-controls">
          <label className="evt-index-date-field">
            <span className="evt-index-date-label">Date from</span>
            <input
              type="date"
              className="evt-index-date-input"
              value={dateAfter}
              onChange={handleDateChange('date_after')}
              aria-label="Date from"
            />
          </label>
          <label className="evt-index-date-field">
            <span className="evt-index-date-label">to</span>
            <input
              type="date"
              className="evt-index-date-input"
              value={dateBefore}
              onChange={handleDateChange('date_before')}
              aria-label="Date to"
            />
          </label>
        </div>

        <div role="status" className="evt-index-summary">
          {loading
            ? 'Loading…'
            : error
              ? `Could not load events: ${error}`
              : totalCount === 0
                ? 'No matching events found.'
                : `${totalCount.toLocaleString()} result${totalCount === 1 ? '' : 's'}`}
        </div>

        {!loading && !error && results.length > 0 && (
          <div className="evt-index-list">
            {results.map(event => (
              <EventCard
                key={event.slug}
                event={event}
                backToSearch={searchParams.toString()}
              />
            ))}
          </div>
        )}

        {!loading && !error && totalCount > PAGE_SIZE && (
          <nav className="evt-index-pagination" aria-label="Pagination">
            <button
              type="button"
              className="evt-index-page-btn"
              onClick={() => goToOffset(offset - PAGE_SIZE)}
              disabled={!hasPrev}
            >
              ← Previous
            </button>
            <span className="evt-index-page-info">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              className="evt-index-page-btn"
              onClick={() => goToOffset(offset + PAGE_SIZE)}
              disabled={!hasNext}
            >
              Next →
            </button>
          </nav>
        )}
      </div>
    </div>
  )
}

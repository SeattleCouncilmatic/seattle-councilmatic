import { useEffect, useState, useRef } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import LegislationCard from './LegislationCard'
import './LegislationIndex.css'

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 300

export default function LegislationIndex() {
  const [searchParams, setSearchParams] = useSearchParams()

  const q = searchParams.get('q') ?? ''
  const status = searchParams.get('status') ?? ''
  const sponsor = searchParams.get('sponsor') ?? ''
  const offset = Number(searchParams.get('offset') ?? 0)

  const [results, setResults] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [statusValues, setStatusValues] = useState([])
  const [sponsorValues, setSponsorValues] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Local input state so typing doesn't immediately fire fetches.
  const [searchInput, setSearchInput] = useState(q)
  const debounceTimer = useRef(null)

  // Sync local input when URL changes from outside (e.g. browser back).
  useEffect(() => { setSearchInput(q) }, [q])

  // Debounce search input → URL.
  useEffect(() => {
    if (searchInput === q) return
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      if (searchInput) next.set('q', searchInput)
      else next.delete('q')
      next.delete('offset')   // reset to first page on new search
      setSearchParams(next, { replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  // Fetch whenever the URL params change.
  useEffect(() => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (status) params.set('status', status)
    if (sponsor) params.set('sponsor', sponsor)
    params.set('limit', PAGE_SIZE)
    params.set('offset', offset)

    fetch(`/api/legislation/?${params.toString()}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => {
        setResults(data.results || [])
        setTotalCount(data.total_count ?? 0)
        if (data.status_values) setStatusValues(data.status_values)
        if (data.sponsor_values) setSponsorValues(data.sponsor_values)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [q, status, sponsor, offset])

  const handleStatusChange = (e) => {
    const next = new URLSearchParams(searchParams)
    if (e.target.value) next.set('status', e.target.value)
    else next.delete('status')
    next.delete('offset')
    setSearchParams(next)
  }

  const handleSponsorChange = (e) => {
    const next = new URLSearchParams(searchParams)
    if (e.target.value) next.set('sponsor', e.target.value)
    else next.delete('sponsor')
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
    <main className="leg-index-page">
      <div className="leg-index-container">
        <nav className="leg-index-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">This Week</Link>
          <span className="leg-index-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="leg-index-breadcrumb-current">Legislation</span>
        </nav>
        <header className="leg-index-header">
          <h1 className="leg-index-title">Legislation</h1>
          <p className="leg-index-subtitle">
            Search and browse all Seattle City Council bills and resolutions.
          </p>
        </header>

        <div className="leg-index-controls">
          <input
            type="search"
            className="leg-index-search"
            placeholder="Search by identifier or title…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search legislation"
            autoFocus
          />
          <select
            className="leg-index-status"
            value={status}
            onChange={handleStatusChange}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {statusValues.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            className="leg-index-status"
            value={sponsor}
            onChange={handleSponsorChange}
            aria-label="Filter by sponsor"
          >
            <option value="">All sponsors</option>
            {sponsorValues.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="leg-index-summary">
          {loading
            ? 'Loading…'
            : error
              ? `Could not load legislation: ${error}`
              : totalCount === 0
                ? 'No matching legislation found.'
                : `${totalCount.toLocaleString()} result${totalCount === 1 ? '' : 's'}`}
        </div>

        {!loading && !error && results.length > 0 && (
          <div className="leg-index-list">
            {results.map(bill => (
              <LegislationCard
                key={bill.identifier}
                bill={bill}
                backToSearch={searchParams.toString()}
              />
            ))}
          </div>
        )}

        {!loading && !error && totalCount > PAGE_SIZE && (
          <nav className="leg-index-pagination" aria-label="Pagination">
            <button
              type="button"
              className="leg-index-page-btn"
              onClick={() => goToOffset(offset - PAGE_SIZE)}
              disabled={!hasPrev}
            >
              ← Previous
            </button>
            <span className="leg-index-page-info">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              className="leg-index-page-btn"
              onClick={() => goToOffset(offset + PAGE_SIZE)}
              disabled={!hasNext}
            >
              Next →
            </button>
          </nav>
        )}
      </div>
    </main>
  )
}

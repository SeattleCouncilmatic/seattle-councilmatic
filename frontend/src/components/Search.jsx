import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search as SearchIcon } from 'lucide-react'
import LegislationCard from './LegislationCard'
import './Search.css'

const TOP_N = 5
const SEARCH_DEBOUNCE_MS = 300

// Unified search across legislation + municipal code. Both endpoints
// already exist; this view fans out two requests in parallel and
// renders the top N of each with type-specific "View all" links to
// the deeper indexes. We don't try to merge ranking across types —
// there's no honest way to compare a bill's relevance to an SMC
// section's, so we stack instead.
export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''

  const [legResults, setLegResults] = useState(null)   // { results, total_count } | null
  const [smcResults, setSmcResults] = useState(null)
  const [loading, setLoading] = useState(false)
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
      setSearchParams(next, { replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  useEffect(() => {
    if (!q) {
      setLegResults(null); setSmcResults(null); setLoading(false); setError(null)
      return
    }
    setLoading(true); setError(null)
    const legParams = new URLSearchParams({ q, limit: String(TOP_N) })
    const smcParams = new URLSearchParams({ q, limit: String(TOP_N) })
    Promise.all([
      fetch(`/api/legislation/?${legParams}`).then(r => r.ok ? r.json() : Promise.reject(new Error(`legislation HTTP ${r.status}`))),
      fetch(`/api/smc/?${smcParams}`).then(r => r.ok ? r.json() : Promise.reject(new Error(`smc HTTP ${r.status}`))),
    ])
      .then(([leg, smc]) => { setLegResults(leg); setSmcResults(smc) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [q])

  return (
    <main className="search-page">
      <div className="search-container">
        <nav className="search-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">This Week</Link>
          <span className="search-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="search-breadcrumb-current">Search</span>
        </nav>

        <header className="search-header">
          <h1 className="search-h1">
            {q ? <>Search results for &ldquo;{q}&rdquo;</> : 'Search'}
          </h1>
          <p className="search-subtitle">
            Searches Seattle legislation and the Municipal Code together.
          </p>
        </header>

        <div className="search-input-wrapper">
          <SearchIcon className="search-input-icon" size={20} aria-hidden="true" />
          <input
            type="search"
            className="search-input"
            placeholder="Search bills, resolutions, and the Municipal Code…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            aria-label="Search Seattle legislation and Municipal Code"
            autoFocus
          />
        </div>

        {!q && (
          <p className="search-empty">Type a keyword or citation above to begin searching.</p>
        )}

        {q && error && <div className="search-error">Could not load: {error}</div>}

        {q && !error && (
          <>
            <SearchSection
              title="Legislation"
              total={legResults?.total_count}
              loading={loading}
              viewAllPath={`/legislation?q=${encodeURIComponent(q)}`}
              empty="No bills or resolutions match this query."
            >
              {legResults?.results?.length > 0 && (
                <div className="search-leg-list">
                  {legResults.results.map(b => (
                    <LegislationCard key={b.identifier} bill={b} backToSearch={searchParams.toString()} />
                  ))}
                </div>
              )}
            </SearchSection>

            <SearchSection
              title="Municipal Code"
              total={smcResults?.total_count}
              loading={loading}
              viewAllPath={`/municode?q=${encodeURIComponent(q)}`}
              empty="No municipal code sections match this query."
            >
              {smcResults?.results?.length > 0 && (
                <ul className="search-smc-list">
                  {smcResults.results.map(r => {
                    const parts = r.section_number.split('.')
                    const path = parts.length === 3
                      ? `/municode/${parts[0]}/${parts[1]}/${parts[2]}`
                      : '#'
                    return (
                      <li key={r.section_number}>
                        <Link to={path} className="search-smc-row">
                          <span className="search-smc-num">{r.section_number}</span>
                          <span className="search-smc-title">{r.title}</span>
                          <span className="search-smc-meta">Ch. {r.chapter_number}</span>
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              )}
            </SearchSection>
          </>
        )}
      </div>
    </main>
  )
}

function SearchSection({ title, total, loading, viewAllPath, empty, children }) {
  const hasResults = total && total > 0
  return (
    <section className="search-section" aria-label={title}>
      <div className="search-section-head">
        <h2 className="search-section-h2">
          {title}
          {typeof total === 'number' && (
            <span className="search-section-count"> ({total.toLocaleString()})</span>
          )}
        </h2>
        {hasResults && total > TOP_N && (
          <Link to={viewAllPath} className="search-section-view-all">
            View all {total.toLocaleString()} results →
          </Link>
        )}
      </div>
      {loading
        ? <div className="search-section-status">Loading…</div>
        : hasResults
          ? children
          : <div className="search-section-status">{empty}</div>}
    </section>
  )
}

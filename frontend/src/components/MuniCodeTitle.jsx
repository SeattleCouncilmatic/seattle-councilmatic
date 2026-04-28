import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { Search as SearchIcon, X as XIcon } from 'lucide-react'
import NotFound from './NotFound'
import NeighborNav from './NeighborNav'
import './MuniCodeDetail.css'

const SCOPED_SEARCH_DEBOUNCE_MS = 300

// Routed at /municode/:slug. The slug is either a title number (e.g. "23"
// or "12A") or a full citation shortcut ("23.47A.004") that we 302 to its
// canonical 3-segment path. The decision is "does it contain a dot" —
// title numbers never do; section/chapter citations always do.
export default function MuniCodeTitle() {
  const { slug } = useParams()

  if (slug.includes('.')) {
    const parts = slug.split('.').filter(Boolean)
    if (parts.length === 2 || parts.length === 3) {
      return <Navigate to={`/municode/${parts.join('/')}`} replace />
    }
    return <NotFound />
  }

  return <TitlePage titleNumber={slug} />
}

function TitlePage({ titleNumber }) {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)
  const [titleSearch, setTitleSearch] = useState('')
  const debounceTimer = useRef(null)

  const navigateToScopedResults = (term) => {
    const trimmed = term.trim()
    if (!trimmed) return
    const params = new URLSearchParams({ q: trimmed, title: titleNumber })
    // Plain push — leaves /municode/<title> in browser history so
    // back-button returns the user here. Once on the index page, its
    // own debounce uses replace:true so further typing won't pollute.
    navigate(`/municode?${params.toString()}`)
  }

  // Auto-navigate after the user pauses typing — matches the live-search
  // behavior of the main index input.
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    if (!titleSearch.trim()) return
    debounceTimer.current = setTimeout(
      () => navigateToScopedResults(titleSearch),
      SCOPED_SEARCH_DEBOUNCE_MS,
    )
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [titleSearch, titleNumber])

  const handleTitleSearch = (e) => {
    e.preventDefault()
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    navigateToScopedResults(titleSearch)
  }

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
    fetch(`/api/smc/titles/${encodeURIComponent(titleNumber)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [titleNumber])

  if (status === 404) return <NotFound />
  if (error) return <ErrorView msg={error} />
  if (!data) return <LoadingView />

  return (
    <main className="smc-detail-page">
      <div className="smc-detail-container">
        <Breadcrumb crumbs={[
          { to: '/', label: 'This Week' },
          { to: '/municode', label: 'Municipal Code' },
          { current: `Title ${data.title_number}` },
        ]} />
        <header className="smc-detail-header">
          <div className="smc-detail-eyebrow">Title {data.title_number}</div>
          <h1 className="smc-detail-h1">{data.name || `Title ${data.title_number}`}</h1>
          <p className="smc-detail-sub">
            {data.chapters.length} chapter{data.chapters.length === 1 ? '' : 's'}
          </p>
        </header>

        <form onSubmit={handleTitleSearch} className="smc-scoped-search" role="search">
          <SearchIcon className="smc-scoped-search-icon" size={18} aria-hidden="true" />
          <input
            type="search"
            className="smc-scoped-search-input"
            placeholder={`Search within Title ${data.title_number}…`}
            value={titleSearch}
            onChange={e => setTitleSearch(e.target.value)}
            aria-label={`Search within Title ${data.title_number}`}
          />
          {titleSearch && (
            <button
              type="button"
              className="smc-scoped-search-clear"
              onClick={() => setTitleSearch('')}
              aria-label="Clear search"
            >
              <XIcon size={16} aria-hidden="true" />
            </button>
          )}
        </form>

        <h2 className="smc-detail-h2">Chapters</h2>
        <ul className="smc-toc-list">
          {data.chapters.map(c => (
            <li key={c.chapter_number}>
              <Link
                to={`/municode/${data.title_number}/${c.chapter_number.split('.').slice(1).join('.')}`}
                className="smc-toc-row"
              >
                <span className="smc-toc-row-label">Chapter {c.chapter_number}</span>
                <span className="smc-toc-row-name">{c.name}</span>
                <span className="smc-toc-row-meta">
                  {c.section_count} section{c.section_count === 1 ? '' : 's'}
                </span>
              </Link>
            </li>
          ))}
        </ul>

        {data.appendices.length > 0 && (
          <>
            <h2 className="smc-detail-h2">Appendices</h2>
            <ul className="smc-listing">
              {data.appendices.map(a => (
                <li key={a.label_slug}>
                  <Link
                    to={`/municode/${data.title_number}/appendix/${a.label_slug}`}
                    className="smc-listing-link"
                  >
                    <span className="smc-listing-num">Appendix {a.label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}

        <NeighborNav neighbors={data.neighbors} ariaLabel="Title navigation" />
      </div>
    </main>
  )
}

function Breadcrumb({ crumbs }) {
  return (
    <nav className="smc-breadcrumb" aria-label="Breadcrumb">
      {crumbs.map((c, i) => (
        <span key={i}>
          {i > 0 && <span className="smc-breadcrumb-sep" aria-hidden="true">/</span>}
          {c.current
            ? <span className="smc-breadcrumb-current">{c.current}</span>
            : <Link to={c.to}>{c.label}</Link>}
        </span>
      ))}
    </nav>
  )
}
export { Breadcrumb }

function LoadingView() {
  return <main className="smc-detail-page"><div className="smc-detail-container">Loading…</div></main>
}
function ErrorView({ msg }) {
  return <main className="smc-detail-page"><div className="smc-detail-container">Could not load: {msg}</div></main>
}
export { LoadingView, ErrorView }

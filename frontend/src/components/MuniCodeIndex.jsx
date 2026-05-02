import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { X as XIcon } from 'lucide-react'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './MuniCodeIndex.css'

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 300

export default function MuniCodeIndex() {
  useDocumentTitle('Municipal Code')
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  const q = searchParams.get('q') ?? ''
  const title = searchParams.get('title') ?? ''
  const chapter = searchParams.get('chapter') ?? ''
  const offset = Number(searchParams.get('offset') ?? 0)

  const [results, setResults] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [mode, setMode] = useState('browse')
  const [tree, setTree] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [searchInput, setSearchInput] = useState(q)
  const debounceTimer = useRef(null)

  useEffect(() => { setSearchInput(q) }, [q])

  // Where to land when the user empties the search input. If they're
  // scoped to a chapter or title, returning to /municode browse mode
  // would force them to navigate back into the scope to search again —
  // instead drop them on the scope page itself, ready for another
  // query. Replace (not push) so the history doesn't accumulate
  // round-trips between the scope page and the search.
  const exitSearchToScope = () => {
    if (chapter) {
      const parts = chapter.split('.')
      navigate(`/municode/${parts[0]}/${parts.slice(1).join('.')}`, { replace: true })
    } else if (title) {
      navigate(`/municode/${title}`, { replace: true })
    } else {
      const next = new URLSearchParams(searchParams)
      next.delete('q')
      next.delete('offset')
      setSearchParams(next, { replace: true })
    }
  }

  useEffect(() => {
    if (searchInput === q) return
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      if (searchInput) {
        const next = new URLSearchParams(searchParams)
        next.set('q', searchInput)
        next.delete('offset')
        setSearchParams(next, { replace: true })
      } else {
        exitSearchToScope()
      }
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  // Load the browse tree once.
  useEffect(() => {
    fetch('/api/smc/tree/')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(setTree)
      .catch(e => setError(e.message))
  }, [])

  // Run the search whenever q/title/chapter/offset change.
  useEffect(() => {
    if (!q) { setResults([]); setTotalCount(0); setMode('browse'); return }
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    params.set('q', q)
    if (title) params.set('title', title)
    if (chapter) params.set('chapter', chapter)
    params.set('limit', PAGE_SIZE)
    params.set('offset', offset)
    fetch(`/api/smc/?${params.toString()}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => {
        setResults(data.results || [])
        setTotalCount(data.total_count ?? 0)
        setMode(data.mode || 'fts')
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [q, title, chapter, offset])

  const clearTitleFilter = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('title')
    next.delete('offset')
    setSearchParams(next)
  }

  const clearChapterFilter = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('chapter')
    next.delete('offset')
    setSearchParams(next)
  }

  // Immediate clear — bypasses the 300ms debounce so the X feels
  // responsive. Both paths (X click and backspace-to-empty) land in
  // the same place via exitSearchToScope.
  const clearSearchImmediately = () => {
    setSearchInput('')
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    exitSearchToScope()
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
    <div className="smc-index-page">
      <div className="smc-index-container">
        <nav className="smc-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="smc-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="smc-breadcrumb-current">Municipal Code</span>
        </nav>
        <header className="smc-index-header">
          <h1 className="smc-index-title">Seattle Municipal Code</h1>
          <p className="smc-index-subtitle">
            Search the SMC by keyword, or browse by title and chapter.
          </p>
        </header>

        <div className="smc-index-controls">
          <div className="smc-index-search-wrapper">
            <input
              type="search"
              className="smc-index-search"
              placeholder="Search the code (e.g. 'short-term rental') or jump to a citation ('23.47A.004')…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              aria-label="Search the Seattle Municipal Code"
              // Search is the primary interaction on this page — autofocus
              // on mount so the user can type immediately. Also covers
              // arriving here from a scoped search submission on a title
              // or chapter page (focus would otherwise be lost when the
              // scope page unmounted).
              autoFocus
            />
            {searchInput && (
              <button
                type="button"
                className="smc-index-search-clear"
                onClick={clearSearchImmediately}
                aria-label="Clear search"
              >
                <XIcon size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        {q && (chapter || title) && (
          <div className="smc-filter-pills" aria-label="Active filters">
            {/* Chapter is more specific than title, so when both are
                somehow set we show the chapter pill only — clearing it
                would still leave the title pill if title were also set. */}
            {chapter ? (
              <span className="smc-filter-pill">
                Filtered to Chapter {chapter}
                <button
                  type="button"
                  className="smc-filter-pill-clear"
                  onClick={clearChapterFilter}
                  aria-label={`Clear chapter ${chapter} filter`}
                >
                  ×
                </button>
              </span>
            ) : (
              <span className="smc-filter-pill">
                Filtered to Title {title}
                <button
                  type="button"
                  className="smc-filter-pill-clear"
                  onClick={clearTitleFilter}
                  aria-label={`Clear title ${title} filter`}
                >
                  ×
                </button>
              </span>
            )}
          </div>
        )}

        {q ? (
          <SearchResults
            loading={loading} error={error} results={results}
            totalCount={totalCount} mode={mode}
            currentPage={currentPage} totalPages={totalPages}
            hasPrev={hasPrev} hasNext={hasNext}
            goToOffset={goToOffset} offset={offset}
          />
        ) : (
          <BrowseTree tree={tree} error={error} />
        )}
      </div>
    </div>
  )
}

function citationToCanonicalPath(section_number) {
  const parts = section_number.split('.')
  if (parts.length !== 3) return null
  return `/municode/${parts[0]}/${parts[1]}/${parts[2]}`
}

function SearchResults({ loading, error, results, totalCount, mode, currentPage,
                        totalPages, hasPrev, hasNext, goToOffset, offset }) {
  return (
    <>
      <div role="status" className="smc-index-summary">
        {loading
          ? 'Loading…'
          : error
            ? `Could not load: ${error}`
            : totalCount === 0
              ? 'No matching sections found.'
              : `${totalCount.toLocaleString()} result${totalCount === 1 ? '' : 's'}${
                  mode === 'citation' ? ' (citation prefix)' : ''
                }`}
      </div>

      {!loading && !error && results.length > 0 && (
        <ul className="smc-result-list">
          {results.map(r => {
            const path = citationToCanonicalPath(r.section_number)
            return (
              <li key={r.section_number} className="smc-result-item">
                <Link className="smc-result-link" to={path ?? '#'}>
                  <span className="smc-result-num">{r.section_number}</span>
                  <span className="smc-result-title">{r.title}</span>
                  {r.subchapter_roman && (
                    <span className="smc-result-sub">
                      Ch. {r.chapter_number} · Subchapter {r.subchapter_roman}
                      {r.subchapter_name ? ` — ${r.subchapter_name}` : ''}
                    </span>
                  )}
                  {!r.subchapter_roman && (
                    <span className="smc-result-sub">Ch. {r.chapter_number}</span>
                  )}
                  {r.snippet && (
                    <span
                      className="smc-result-snippet"
                      // Backend HTML-escapes the snippet and only restores
                      // <mark> sentinels, so anything tag-shaped in the
                      // source renders as text. Safe to feed to
                      // dangerouslySetInnerHTML.
                      dangerouslySetInnerHTML={{ __html: r.snippet }}
                    />
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      {!loading && !error && totalCount > results.length && (
        <nav className="smc-pagination" aria-label="Pagination">
          <button type="button" className="smc-page-btn"
                  onClick={() => goToOffset(offset - PAGE_SIZE)} disabled={!hasPrev}>
            ← Previous
          </button>
          <span className="smc-page-info">Page {currentPage} of {totalPages}</span>
          <button type="button" className="smc-page-btn"
                  onClick={() => goToOffset(offset + PAGE_SIZE)} disabled={!hasNext}>
            Next →
          </button>
        </nav>
      )}
    </>
  )
}

function BrowseTree({ tree, error }) {
  if (error) return <div role="alert" className="smc-index-summary">Could not load: {error}</div>
  if (!tree) return <div role="status" className="smc-index-summary">Loading titles…</div>

  return (
    <section className="smc-browse" aria-label="Browse by title">
      <h2 className="smc-browse-heading">Browse by Title</h2>
      <ul className="smc-toc-list">
        {tree.titles.map(t => {
          const totalSections = t.chapters.reduce((sum, c) => sum + c.section_count, 0)
          return (
            <li key={t.title_number}>
              <Link to={`/municode/${t.title_number}`} className="smc-toc-row">
                <span className="smc-toc-row-label">Title {t.title_number}</span>
                <span className="smc-toc-row-name">{t.name}</span>
                <span className="smc-toc-row-meta">
                  {t.chapters.length} chapter{t.chapters.length === 1 ? '' : 's'} ·{' '}
                  {totalSections.toLocaleString()} section{totalSections === 1 ? '' : 's'}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>

      {tree.appendices.length > 0 && (
        <>
          <h2 className="smc-browse-heading">Appendices</h2>
          <ul className="smc-toc-list">
            {tree.appendices.map(a => (
              <li key={`${a.title_number}-${a.label_slug}`}>
                <Link to={`/municode/${a.title_number}/appendix/${a.label_slug}`}
                      className="smc-toc-row">
                  <span className="smc-toc-row-label">Title {a.title_number}</span>
                  <span className="smc-toc-row-name">Appendix {a.label}</span>
                  <span className="smc-toc-row-meta"></span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {tree.source_pdf && (
        <>
          <h2 className="smc-browse-heading">Source</h2>
          <p className="smc-source-pdf">
            The complete Seattle Municipal Code is also available as a single PDF.
            <a
              href={tree.source_pdf.url}
              download={tree.source_pdf.filename}
              className="smc-source-pdf-btn"
            >
              Download PDF ({Math.round(tree.source_pdf.size_bytes / 1_000_000)} MB)
            </a>
          </p>
        </>
      )}
    </section>
  )
}

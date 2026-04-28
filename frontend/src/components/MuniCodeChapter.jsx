import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Search as SearchIcon, X as XIcon } from 'lucide-react'
import NotFound from './NotFound'
import NeighborNav from './NeighborNav'
import { Breadcrumb, LoadingView, ErrorView } from './MuniCodeTitle'
import './MuniCodeDetail.css'

const SCOPED_SEARCH_DEBOUNCE_MS = 300

export default function MuniCodeChapter() {
  const { title, chapter } = useParams()
  const navigate = useNavigate()
  // URL form is /municode/<title>/<chapter-short>; the API takes the full
  // dotted form (`23.47A`), so we reconstruct it.
  const fullChapter = `${title}.${chapter}`

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)
  const [chapterSearch, setChapterSearch] = useState('')
  const debounceTimer = useRef(null)

  const navigateToScopedResults = (term) => {
    const trimmed = term.trim()
    if (!trimmed) return
    const params = new URLSearchParams({ q: trimmed, chapter: fullChapter })
    // Plain push — leaves /municode/<chapter> in browser history so
    // back-button returns the user here. Once on the index page, its
    // own debounce uses replace:true so further typing won't pollute.
    navigate(`/municode?${params.toString()}`)
  }

  // Auto-navigate after the user pauses typing. Mirrors the live-search
  // behavior on the main index page so both feel the same.
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    if (!chapterSearch.trim()) return
    debounceTimer.current = setTimeout(
      () => navigateToScopedResults(chapterSearch),
      SCOPED_SEARCH_DEBOUNCE_MS,
    )
    return () => clearTimeout(debounceTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterSearch, fullChapter])

  const handleChapterSearch = (e) => {
    e.preventDefault()
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    navigateToScopedResults(chapterSearch)
  }

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
    fetch(`/api/smc/chapters/${encodeURIComponent(fullChapter)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [fullChapter])

  if (status === 404) return <NotFound />
  if (error) return <ErrorView msg={error} />
  if (!data) return <LoadingView />

  return (
    <main className="smc-detail-page">
      <div className="smc-detail-container">
        <Breadcrumb crumbs={[
          { to: '/', label: 'This Week' },
          { to: '/municode', label: 'Municipal Code' },
          { to: `/municode/${data.title_number}`, label: `Title ${data.title_number}` },
          { current: `Chapter ${data.chapter_number}` },
        ]} />
        <header className="smc-detail-header">
          <div className="smc-detail-eyebrow">Chapter {data.chapter_number}</div>
          <h1 className="smc-detail-h1">{data.chapter_name || `Chapter ${data.chapter_number}`}</h1>
          {data.title_name && (
            <p className="smc-detail-sub">Title {data.title_number} · {data.title_name}</p>
          )}
        </header>

        <form onSubmit={handleChapterSearch} className="smc-scoped-search" role="search">
          <SearchIcon className="smc-scoped-search-icon" size={18} aria-hidden="true" />
          <input
            type="search"
            className="smc-scoped-search-input"
            placeholder={`Search within Chapter ${data.chapter_number}…`}
            value={chapterSearch}
            onChange={e => setChapterSearch(e.target.value)}
            aria-label={`Search within Chapter ${data.chapter_number}`}
            autoFocus
          />
          {chapterSearch && (
            <button
              type="button"
              className="smc-scoped-search-clear"
              onClick={() => setChapterSearch('')}
              aria-label="Clear search"
            >
              <XIcon size={16} aria-hidden="true" />
            </button>
          )}
        </form>

        {data.groups.map((g, i) => (
          <section key={i} className="smc-chapter-group">
            {g.subchapter ? (
              <h2 className="smc-detail-h2">
                Subchapter {g.subchapter.roman}
                {g.subchapter.name ? ` — ${g.subchapter.name}` : ''}
              </h2>
            ) : null}
            {g.sections.length === 0 ? (
              <p className="smc-empty">No sections in this subchapter were captured by the parser.</p>
            ) : (
              <ul className="smc-toc-list">
                {g.sections.map(s => {
                  const parts = s.section_number.split('.')
                  const path = parts.length === 3
                    ? `/municode/${parts[0]}/${parts[1]}/${parts[2]}`
                    : '#'
                  return (
                    <li key={s.section_number}>
                      <Link to={path} className="smc-toc-row">
                        <span className="smc-toc-row-label">Section {s.section_number}</span>
                        <span className="smc-toc-row-name">{s.title}</span>
                        <span className="smc-toc-row-meta">
                          {s.has_summary && <span className="smc-summary-badge">Plain summary</span>}
                        </span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        ))}

        <NeighborNav neighbors={data.neighbors} ariaLabel="Chapter navigation" />
      </div>
    </main>
  )
}

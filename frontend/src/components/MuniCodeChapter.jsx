import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import NotFound from './NotFound'
import { Breadcrumb, LoadingView, ErrorView } from './MuniCodeTitle'
import './MuniCodeDetail.css'

export default function MuniCodeChapter() {
  const { title, chapter } = useParams()
  // URL form is /municode/<title>/<chapter-short>; the API takes the full
  // dotted form (`23.47A`), so we reconstruct it.
  const fullChapter = `${title}.${chapter}`

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)

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
          <h1 className="smc-detail-h1">Chapter {data.chapter_number}</h1>
        </header>

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
              <ul className="smc-listing">
                {g.sections.map(s => {
                  const parts = s.section_number.split('.')
                  const path = parts.length === 3
                    ? `/municode/${parts[0]}/${parts[1]}/${parts[2]}`
                    : '#'
                  return (
                    <li key={s.section_number}>
                      <Link to={path} className="smc-listing-link">
                        <span className="smc-listing-num">{s.section_number}</span>
                        <span className="smc-listing-title">{s.title}</span>
                        {s.has_summary && <span className="smc-summary-badge">Plain summary</span>}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        ))}
      </div>
    </main>
  )
}

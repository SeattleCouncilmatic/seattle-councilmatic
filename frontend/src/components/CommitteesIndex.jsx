import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, Users, CalendarDays } from 'lucide-react'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './CommitteesIndex.css'

function formatMeetingDate(isoString) {
  if (!isoString) return null
  const d = new Date(isoString)
  if (isNaN(d.getTime())) return null
  return d.toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function CommitteesIndex() {
  useDocumentTitle('Committees')
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    fetch('/api/committees/')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(setData)
      .catch(e => setLoadError(e.message))
  }, [])

  return (
    <div className="cmte-page">
      <div className="cmte-container">
        <nav className="cmte-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="cmte-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="cmte-breadcrumb-current">Committees</span>
        </nav>

        <header className="cmte-header">
          <h1 className="cmte-h1">City Council Committees</h1>
          <p className="cmte-subtitle">
            Standing committees do the council's detailed work — reviewing
            legislation, holding hearings, and shaping policy before it reaches
            the full council. Browse each committee's members, meetings, and
            the bills before it.
          </p>
        </header>

        {loadError && (
          <div className="cmte-alert" role="alert">
            <AlertCircle size={20} aria-hidden="true" />
            <span>Could not load committees: {loadError}</span>
          </div>
        )}

        {!data && !loadError && (
          <p role="status" className="cmte-loading">Loading…</p>
        )}

        {data && (
          <ul className="cmte-card-grid">
            {data.results.map(c => (
              <li key={c.slug}>
                <Link to={`/committees/${c.slug}`} className="cmte-card">
                  <h2 className="cmte-card-name">{c.name}</h2>
                  {c.chair && (
                    <p className="cmte-card-chair">
                      <span className="cmte-card-chair-label">Chair</span>
                      {c.chair}
                    </p>
                  )}
                  <div className="cmte-card-meta">
                    <span className="cmte-card-meta-item">
                      <Users size={14} aria-hidden="true" />
                      {c.member_count} {c.member_count === 1 ? 'member' : 'members'}
                    </span>
                    {c.next_meeting && (
                      <span className="cmte-card-meta-item">
                        <CalendarDays size={14} aria-hidden="true" />
                        Next: {formatMeetingDate(c.next_meeting)}
                      </span>
                    )}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

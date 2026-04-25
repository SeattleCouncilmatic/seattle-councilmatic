import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import NotFound from './NotFound'
import './MeetingDetail.css'

function formatDateTime(isoString) {
  if (!isoString) return '—'
  const d = new Date(isoString)
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}

function StatusBadge({ status }) {
  const MAP = {
    confirmed: { label: 'Confirmed', cls: 'meeting-badge--confirmed' },
    tentative:  { label: 'Tentative', cls: 'meeting-badge--tentative' },
    cancelled:  { label: 'Cancelled', cls: 'meeting-badge--cancelled' },
  }
  const { label, cls } = MAP[status?.toLowerCase()] ?? { label: status, cls: '' }
  return <span className={`meeting-badge ${cls}`}>{label}</span>
}

export default function MeetingDetail() {
  const { slug } = useParams()
  const [meeting, setMeeting] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    fetch(`/api/meetings/${slug}/`)
      .then(r => {
        if (r.status === 404) {
          setNotFound(true)
          setLoading(false)
          return null
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (data) { setMeeting(data); setLoading(false) }
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [slug])

  if (loading)  return <div className="mtg-detail-loading">Loading…</div>
  if (notFound) return <NotFound kind="meeting" />
  if (error)    return <div className="mtg-detail-error">Could not load meeting: {error}</div>

  const legistarUrl = meeting.legistar_url || null

  return (
    <main className="mtg-detail-page">
      <div className="mtg-detail-container">

        {/* Back link */}
        <Link to="/" className="mtg-detail-back">← Back to This Week</Link>

        {/* Header */}
        <header className="mtg-detail-header">
          <h1 className="mtg-detail-title">{meeting.name}</h1>
          <div className="mtg-detail-meta-row">
            <StatusBadge status={meeting.status} />
          </div>
        </header>

        {/* Body */}
        <div className="mtg-detail-body">

          {/* Sidebar: key facts */}
          <aside className="mtg-detail-sidebar">
            <section className="mtg-detail-section">
              <h2 className="mtg-detail-section-title">Details</h2>
              <dl className="mtg-detail-dl">
                <dt>Date &amp; Time</dt>
                <dd>{formatDateTime(meeting.start_date)}</dd>

                {meeting.end_date && (
                  <>
                    <dt>Ends</dt>
                    <dd>{formatDateTime(meeting.end_date)}</dd>
                  </>
                )}

                {meeting.location && (
                  <>
                    <dt>Location</dt>
                    <dd className="mtg-detail-location">{meeting.location}</dd>
                  </>
                )}

                {legistarUrl && (
                  <>
                    <dt>Legistar</dt>
                    <dd>
                      <a
                        href={legistarUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mtg-detail-external-link"
                      >
                        View on Legistar ↗
                      </a>
                    </dd>
                  </>
                )}
              </dl>
            </section>
          </aside>

          {/* Main: description (or placeholder) */}
          <section className="mtg-detail-main">
            <h2 className="mtg-detail-section-title">About This Meeting</h2>
            {meeting.description ? (
              <p className="mtg-detail-description">{meeting.description}</p>
            ) : (
              <p className="mtg-detail-empty">
                No additional details available. Check the{' '}
                {legistarUrl ? (
                  <a
                    href={legistarUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mtg-detail-external-link"
                  >
                    Legistar event page
                  </a>
                ) : 'Legistar'}{' '}
                for agenda and documents.
              </p>
            )}
          </section>

        </div>
      </div>
    </main>
  )
}

import { useEffect, useState } from 'react'
import { useParams, useLocation, Link } from 'react-router-dom'
import NotFound from './NotFound'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './EventDetail.css'

function formatDateTime(isoString) {
  if (!isoString) return '—'
  const d = new Date(isoString)
  return d.toLocaleString('en-US', {
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
    confirmed: { label: 'Confirmed', cls: 'evt-badge--confirmed' },
    tentative:  { label: 'Tentative', cls: 'evt-badge--tentative' },
    cancelled:  { label: 'Cancelled', cls: 'evt-badge--cancelled' },
  }
  const { label, cls } = MAP[status?.toLowerCase()] ?? { label: status, cls: '' }
  return <span className={`evt-badge ${cls}`}>{label}</span>
}

function MatterChip({ type }) {
  if (!type) return null
  // Extract the short code from e.g. "Council Bill (CB)" → "CB"
  const match = type.match(/\(([^)]+)\)$/)
  const code = match ? match[1] : type
  const cls =
    code === 'CB'  ? 'matter-chip--cb'  :
    code === 'Res' ? 'matter-chip--res' :
    code === 'Inf' ? 'matter-chip--inf' : 'matter-chip--other'
  return <span className={`matter-chip ${cls}`}>{code}</span>
}

function DocIcon({ mediaType }) {
  if (mediaType === 'application/pdf') return <span className="evt-att-icon evt-att-icon--pdf">PDF</span>
  if (mediaType?.includes('word'))     return <span className="evt-att-icon evt-att-icon--doc">DOC</span>
  return <span className="evt-att-icon">FILE</span>
}

function AgendaDocButtons({ agendaUrl, agendaStatus, packetUrl, minutesUrl, minutesStatus }) {
  if (!agendaUrl && !packetUrl && !minutesUrl) return null
  return (
    <div className="evt-docs-row">
      {agendaUrl && (
        <a href={agendaUrl} target="_blank" rel="noopener noreferrer" className="evt-doc-btn evt-doc-btn--agenda">
          <span className="evt-doc-btn-icon">📄</span>
          Agenda
          {agendaStatus && <span className="evt-doc-btn-status">{agendaStatus}</span>}
        </a>
      )}
      {packetUrl && (
        <a href={packetUrl} target="_blank" rel="noopener noreferrer" className="evt-doc-btn evt-doc-btn--packet">
          <span className="evt-doc-btn-icon">📦</span>
          Agenda Packet
        </a>
      )}
      {minutesUrl && (
        <a href={minutesUrl} target="_blank" rel="noopener noreferrer" className="evt-doc-btn evt-doc-btn--minutes">
          <span className="evt-doc-btn-icon">📋</span>
          Minutes
          {minutesStatus && <span className="evt-doc-btn-status">{minutesStatus}</span>}
        </a>
      )}
    </div>
  )
}

function AgendaItemRow({ item, index }) {
  const { description, matter_file, matter_type, matter_status, bill_slug, attachments, action_text } = item

  const titleNode = bill_slug ? (
    <Link to={`/legislation/${bill_slug}`} className="evt-agenda-link">{description}</Link>
  ) : (
    <span>{description}</span>
  )

  return (
    <li className="evt-agenda-item">
      <div className="evt-agenda-item-header">
        <span className="evt-agenda-seq">{index + 1}.</span>
        <div className="evt-agenda-item-body">
          <div className="evt-agenda-title-row">
            <MatterChip type={matter_type} />
            <span className="evt-agenda-title">{titleNode}</span>
          </div>
          <div className="evt-agenda-meta">
            {matter_file && <span className="evt-agenda-file">{matter_file}</span>}
            {matter_status && <span className="evt-agenda-status">{matter_status}</span>}
            {action_text && <span className="evt-agenda-action">{action_text}</span>}
          </div>
          {attachments?.length > 0 && (
            <ul className="evt-att-list">
              {attachments.map((att, i) => (
                <li key={i} className="evt-att-item">
                  <DocIcon mediaType={att.media_type} />
                  <a href={att.url} target="_blank" rel="noopener noreferrer" className="evt-att-link">
                    {att.name}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </li>
  )
}

export default function EventDetail() {
  const { slug } = useParams()
  const location = useLocation()
  // If we arrived via a card on the events index, the current search params
  // are stashed in location.state.backToSearch so the breadcrumb can return
  // to the same filtered view. Direct deep links and ThisWeek cards have no
  // state and fall back to a fresh /events.
  const eventsHref = location.state?.backToSearch
    ? `/events?${location.state.backToSearch}`
    : '/events'

  const [event, setEvent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notFound, setNotFound] = useState(false)
  useDocumentTitle(event?.name)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    fetch(`/api/events/${slug}/`)
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
        if (data) { setEvent(data); setLoading(false) }
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [slug])

  if (loading)  return <div role="status" className="evt-detail-loading">Loading…</div>
  if (notFound) return <NotFound kind="event" />
  if (error)    return <div role="alert" className="evt-detail-error">Could not load event: {error}</div>

  const legistarUrl = event.legistar_url || null
  // Filter out items that have no matter_file and no attachments (pure procedural notes)
  const substantiveItems = (event.agenda_items || []).filter(
    item => item.matter_file || (item.attachments && item.attachments.length > 0)
  )

  return (
    <div className="evt-detail-page">
      <div className="evt-detail-container">

        {/* Breadcrumb */}
        <nav className="evt-detail-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="evt-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <Link to={eventsHref}>Events</Link>
          <span className="evt-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="evt-detail-breadcrumb-current">{event.name}</span>
        </nav>

        {/* Header */}
        <header className="evt-detail-header">
          <h1 className="evt-detail-title">{event.name}</h1>
          <div className="evt-detail-meta-row">
            <StatusBadge status={event.status} />
          </div>
        </header>

        {/* Agenda & Minutes PDF buttons */}
        <AgendaDocButtons
          agendaUrl={event.agenda_file_url}
          agendaStatus={event.agenda_status}
          packetUrl={event.packet_url}
          minutesUrl={event.minutes_file_url}
          minutesStatus={event.minutes_status}
        />

        {/* Body */}
        <div className="evt-detail-body">

          {/* Sidebar: key facts */}
          <aside className="evt-detail-sidebar">
            <section className="evt-detail-section">
              <h2 className="evt-detail-section-title">Details</h2>
              <dl className="evt-detail-dl">
                <dt>Date &amp; Time</dt>
                <dd>{formatDateTime(event.start_date)}</dd>

                {event.end_date && (
                  <>
                    <dt>Ends</dt>
                    <dd>{formatDateTime(event.end_date)}</dd>
                  </>
                )}

                {event.location && (
                  <>
                    <dt>Location</dt>
                    <dd className="evt-detail-location">{event.location}</dd>
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
                        className="evt-detail-external-link"
                      >
                        View on Legistar ↗
                      </a>
                    </dd>
                  </>
                )}
              </dl>
            </section>
          </aside>

          {/* Main: agenda items */}
          <section className="evt-detail-main">
            <h2 className="evt-detail-section-title">Agenda Items</h2>
            {substantiveItems.length === 0 ? (
              <p className="evt-detail-empty">
                No agenda items available. Check the{' '}
                {legistarUrl ? (
                  <a href={legistarUrl} target="_blank" rel="noopener noreferrer" className="evt-detail-external-link">
                    Legistar event page
                  </a>
                ) : 'Legistar'}{' '}
                for the full agenda.
              </p>
            ) : (
              <ol className="evt-agenda-list">
                {substantiveItems.map((item, i) => (
                  <AgendaItemRow key={i} item={item} index={i} />
                ))}
              </ol>
            )}
          </section>

        </div>
      </div>
    </div>
  )
}

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
  if (mediaType === 'application/pdf') return <span className="mtg-att-icon mtg-att-icon--pdf">PDF</span>
  if (mediaType?.includes('word'))     return <span className="mtg-att-icon mtg-att-icon--doc">DOC</span>
  return <span className="mtg-att-icon">FILE</span>
}

function AgendaDocButtons({ agendaUrl, agendaStatus, packetUrl, minutesUrl, minutesStatus }) {
  if (!agendaUrl && !packetUrl && !minutesUrl) return null
  return (
    <div className="mtg-docs-row">
      {agendaUrl && (
        <a href={agendaUrl} target="_blank" rel="noopener noreferrer" className="mtg-doc-btn mtg-doc-btn--agenda">
          <span className="mtg-doc-btn-icon">📄</span>
          Agenda
          {agendaStatus && <span className="mtg-doc-btn-status">{agendaStatus}</span>}
        </a>
      )}
      {packetUrl && (
        <a href={packetUrl} target="_blank" rel="noopener noreferrer" className="mtg-doc-btn mtg-doc-btn--packet">
          <span className="mtg-doc-btn-icon">📦</span>
          Agenda Packet
        </a>
      )}
      {minutesUrl && (
        <a href={minutesUrl} target="_blank" rel="noopener noreferrer" className="mtg-doc-btn mtg-doc-btn--minutes">
          <span className="mtg-doc-btn-icon">📋</span>
          Minutes
          {minutesStatus && <span className="mtg-doc-btn-status">{minutesStatus}</span>}
        </a>
      )}
    </div>
  )
}

function AgendaItemRow({ item, index }) {
  const { description, matter_file, matter_type, matter_status, bill_slug, attachments, action_text } = item

  const titleNode = bill_slug ? (
    <Link to={`/legislation/${bill_slug}`} className="mtg-agenda-link">{description}</Link>
  ) : (
    <span>{description}</span>
  )

  return (
    <li className="mtg-agenda-item">
      <div className="mtg-agenda-item-header">
        <span className="mtg-agenda-seq">{index + 1}.</span>
        <div className="mtg-agenda-item-body">
          <div className="mtg-agenda-title-row">
            <MatterChip type={matter_type} />
            <span className="mtg-agenda-title">{titleNode}</span>
          </div>
          <div className="mtg-agenda-meta">
            {matter_file && <span className="mtg-agenda-file">{matter_file}</span>}
            {matter_status && <span className="mtg-agenda-status">{matter_status}</span>}
            {action_text && <span className="mtg-agenda-action">{action_text}</span>}
          </div>
          {attachments?.length > 0 && (
            <ul className="mtg-att-list">
              {attachments.map((att, i) => (
                <li key={i} className="mtg-att-item">
                  <DocIcon mediaType={att.media_type} />
                  <a href={att.url} target="_blank" rel="noopener noreferrer" className="mtg-att-link">
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
  // Filter out items that have no matter_file and no attachments (pure procedural notes)
  const substantiveItems = (meeting.agenda_items || []).filter(
    item => item.matter_file || (item.attachments && item.attachments.length > 0)
  )

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

        {/* Agenda & Minutes PDF buttons */}
        <AgendaDocButtons
          agendaUrl={meeting.agenda_file_url}
          agendaStatus={meeting.agenda_status}
          packetUrl={meeting.packet_url}
          minutesUrl={meeting.minutes_file_url}
          minutesStatus={meeting.minutes_status}
        />

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

          {/* Main: agenda items */}
          <section className="mtg-detail-main">
            <h2 className="mtg-detail-section-title">Agenda Items</h2>
            {substantiveItems.length === 0 ? (
              <p className="mtg-detail-empty">
                No agenda items available. Check the{' '}
                {legistarUrl ? (
                  <a href={legistarUrl} target="_blank" rel="noopener noreferrer" className="mtg-detail-external-link">
                    Legistar event page
                  </a>
                ) : 'Legistar'}{' '}
                for the full agenda.
              </p>
            ) : (
              <ol className="mtg-agenda-list">
                {substantiveItems.map((item, i) => (
                  <AgendaItemRow key={i} item={item} index={i} />
                ))}
              </ol>
            )}
          </section>

        </div>
      </div>
    </main>
  )
}

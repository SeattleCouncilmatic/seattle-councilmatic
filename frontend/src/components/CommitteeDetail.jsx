import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ExternalLink, Users } from 'lucide-react'
import NotFound from './NotFound'
import EventCard from './EventCard'
import LegislationCard from './LegislationCard'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './CommitteeDetail.css'

function roleClass(role) {
  return `cmte-roster-role cmte-roster-role--${(role || '').toLowerCase().replace(/[^a-z]/g, '-')}`
}

export default function CommitteeDetail() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)
  useDocumentTitle(data?.name)

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
    fetch(`/api/committees/${encodeURIComponent(slug)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [slug])

  if (status === 404) return <NotFound />
  if (error) return (
    <div className="cmte-detail-page">
      <div role="alert" className="cmte-detail-container">Could not load committee: {error}</div>
    </div>
  )
  if (!data) return (
    <div className="cmte-detail-page">
      <div role="status" className="cmte-detail-container">Loading…</div>
    </div>
  )

  // All meetings of a committee share one Event.name, so the first
  // available card's name is the filter value for the events index
  // (which hydrates `committee` + `time` from the URL).
  const eventName = (data.upcoming_meetings[0] || data.recent_meetings[0])?.name
  const allMeetingsHref = eventName
    ? `/events?committee=${encodeURIComponent(eventName)}&time=all`
    : null

  const hasUpcoming = data.upcoming_meetings.length > 0
  const hasRecent = data.recent_meetings.length > 0
  const hasMeetings = hasUpcoming || hasRecent
  const hasBills = data.bills.length > 0
  const moreBills = data.bills_total > data.bills.length
  // Two columns (bills | meetings, mirroring the home screen) only when
  // both sides have content; otherwise the lone side renders full width.
  const twoCol = hasMeetings && hasBills

  return (
    <div className="cmte-detail-page">
      <div className="cmte-detail-container">
        <nav className="cmte-detail-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="cmte-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <Link to="/committees">Committees</Link>
          <span className="cmte-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="cmte-detail-breadcrumb-current">{data.name}</span>
        </nav>

        <header className="cmte-detail-header">
          <div className="cmte-detail-eyebrow">Committee</div>
          <h1 className="cmte-detail-h1">{data.name}</h1>
          <div className="cmte-detail-meta">
            <span className="cmte-detail-meta-item">
              <Users size={15} aria-hidden="true" />
              {data.member_count} {data.member_count === 1 ? 'member' : 'members'}
            </span>
            {data.source_url && (
              <a href={data.source_url} target="_blank" rel="noopener noreferrer"
                 className="cmte-detail-source-link">
                <ExternalLink size={14} aria-hidden="true" />
                seattle.gov page
              </a>
            )}
          </div>
        </header>

        {data.roster.length > 0 && (
          <section className="cmte-detail-section" aria-labelledby="cmte-roster-h2">
            <h2 id="cmte-roster-h2" className="cmte-detail-section-h2">Members</h2>
            <ul className="cmte-roster">
              {data.roster.map(m => {
                const inner = (
                  <>
                    {m.image && (
                      <img className="cmte-roster-photo" src={m.image} alt="" />
                    )}
                    <div className="cmte-roster-body">
                      <span className={roleClass(m.role)}>{m.role}</span>
                      <span className="cmte-roster-name">{m.name}</span>
                    </div>
                  </>
                )
                return (
                  <li key={m.name} className="cmte-roster-item">
                    {m.slug
                      ? <Link to={`/reps/${m.slug}`} className="cmte-roster-link">{inner}</Link>
                      : <div className="cmte-roster-link cmte-roster-link--static">{inner}</div>}
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {(hasMeetings || hasBills) && (
          <div className={`cmte-detail-columns${twoCol ? ' cmte-detail-columns--two' : ''}`}>

            {hasBills && (
              <div className="cmte-detail-col">
                <section className="cmte-detail-section" aria-labelledby="cmte-bills-h2">
                  <h2 id="cmte-bills-h2" className="cmte-detail-section-h2">
                    Bills considered by this committee
                    <span className="cmte-detail-section-count"> ({data.bills_total})</span>
                  </h2>
                  <div className="cmte-bill-list">
                    {data.bills.map(bill => (
                      <LegislationCard key={bill.slug || bill.identifier} bill={bill} />
                    ))}
                  </div>
                  {moreBills && (
                    <p className="cmte-detail-more-note">
                      Showing the {data.bills.length} most recent of {data.bills_total}.
                    </p>
                  )}
                </section>
              </div>
            )}

            {hasMeetings && (
              <div className="cmte-detail-col">
                {/* Always shown — committees meet on staggered schedules and
                    often have no future meeting posted yet, so an empty state
                    is more reassuring than a missing section. */}
                <section className="cmte-detail-section" aria-labelledby="cmte-upcoming-h2">
                  <h2 id="cmte-upcoming-h2" className="cmte-detail-section-h2">Upcoming meetings</h2>
                  {hasUpcoming ? (
                    <div className="cmte-meeting-list">
                      {data.upcoming_meetings.map(ev => (
                        <EventCard key={ev.slug} event={ev} />
                      ))}
                    </div>
                  ) : (
                    <p className="cmte-detail-meetings-empty">No upcoming meetings scheduled.</p>
                  )}
                </section>

                {hasRecent && (
                  <section className="cmte-detail-section" aria-labelledby="cmte-recent-h2">
                    <h2 id="cmte-recent-h2" className="cmte-detail-section-h2">Recent meetings</h2>
                    <div className="cmte-meeting-list">
                      {data.recent_meetings.map(ev => (
                        <EventCard key={ev.slug} event={ev} />
                      ))}
                    </div>
                    {allMeetingsHref && (
                      <Link to={allMeetingsHref} className="cmte-detail-more-link">
                        View all meetings →
                      </Link>
                    )}
                  </section>
                )}
              </div>
            )}

          </div>
        )}

        {!data.roster.length && !hasMeetings && !hasBills && (
          <p className="cmte-detail-empty">
            No activity is currently recorded for this committee.
          </p>
        )}
      </div>
    </div>
  )
}

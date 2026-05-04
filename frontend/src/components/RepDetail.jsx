import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Phone, Mail, Printer, MapPin, ExternalLink, Clock } from 'lucide-react'
import NotFound from './NotFound'
import LegislationInvolvementTable from './LegislationInvolvementTable'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './RepDetail.css'

// Order in which lifetime option tallies appear in the breakdown row
// above the legislation involvement table. Keys match `_OPTION_LABELS`
// on the API side.
const VOTE_OPTION_ORDER = ['yes', 'no', 'abstain', 'absent', 'excused', 'not voting', 'other']

const optionSlug = (s) => s.replace(/\s+/g, '-')

const optionTitle = (opt) =>
  opt === 'not voting' ? 'Not voting' : opt.charAt(0).toUpperCase() + opt.slice(1)

export default function RepDetail() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)
  // The activity stats pills double as filters on the involvement
  // table below. `activeFilter` is `{kind, value}` or null; click a
  // pill to set it, click again to clear, click another to switch.
  // Resets to null whenever the rep changes.
  const [activeFilter, setActiveFilter] = useState(null)
  useDocumentTitle(data?.name)

  useEffect(() => {
    setData(null); setError(null); setStatus(null); setActiveFilter(null)
    fetch(`/api/reps/${encodeURIComponent(slug)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [slug])

  function togglePill(kind, value) {
    setActiveFilter(prev =>
      prev && prev.kind === kind && prev.value === value ? null : { kind, value }
    )
  }
  function isPressed(kind, value) {
    return activeFilter?.kind === kind && activeFilter?.value === value
  }

  if (status === 404) return <NotFound />
  if (error) return (
    <div className="rep-detail-page"><div role="alert" className="rep-detail-container">Could not load: {error}</div></div>
  )
  if (!data) return (
    <div className="rep-detail-page"><div role="status" className="rep-detail-container">Loading…</div></div>
  )

  // Sponsorship breakdown — computed from `legislation_involvement` so
  // the activity stats strip stays in sync with the table without a
  // second API trip. The table already has the per-row sponsorship
  // marker; we just tally it.
  const sponsorshipCounts = (data.legislation_involvement || []).reduce(
    (acc, r) => {
      if (r.sponsorship === 'primary')   acc.primary++
      if (r.sponsorship === 'cosponsor') acc.cosponsor++
      return acc
    },
    { primary: 0, cosponsor: 0 }
  )
  const hasActivity =
    (data.voting_history?.total || 0) > 0 ||
    sponsorshipCounts.primary > 0 ||
    sponsorshipCounts.cosponsor > 0

  return (
    <div className="rep-detail-page">
      <div className="rep-detail-container">
        <nav className="rep-detail-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="rep-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <Link to="/reps">City Council</Link>
          <span className="rep-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="rep-detail-breadcrumb-current">{data.name}</span>
        </nav>

        <div className="rep-detail-grid">
          <header className="rep-detail-rail">
            {data.image && (
              <figure className="rep-detail-photo">
                <img src={data.image} alt={`Councilmember ${data.name}`} />
              </figure>
            )}
            <div className="rep-detail-eyebrow">{data.district}</div>
            <h1 className="rep-detail-h1">{data.name}</h1>
            {data.district_description && (
              <p className="rep-detail-sub">{data.district_description}</p>
            )}

            <section className="rep-detail-contacts" aria-label="Contact">
              {data.phone && (
                <div className="rep-detail-contact-row">
                  <Phone size={16} aria-hidden="true" />
                  <div>
                    <div className="rep-detail-contact-label">Phone</div>
                    <a href={`tel:${data.phone}`} className="rep-detail-contact-value">{data.phone}</a>
                  </div>
                </div>
              )}
              {data.email && (
                <div className="rep-detail-contact-row">
                  <Mail size={16} aria-hidden="true" />
                  <div>
                    <div className="rep-detail-contact-label">Email</div>
                    <a href={`mailto:${data.email}`} className="rep-detail-contact-value">{data.email}</a>
                  </div>
                </div>
              )}
              {data.fax && (
                <div className="rep-detail-contact-row">
                  <Printer size={16} aria-hidden="true" />
                  <div>
                    <div className="rep-detail-contact-label">Fax</div>
                    <div className="rep-detail-contact-value rep-detail-contact-static">{data.fax}</div>
                  </div>
                </div>
              )}
              {data.office_address && (
                <div className="rep-detail-contact-row">
                  <MapPin size={16} aria-hidden="true" />
                  <div>
                    <div className="rep-detail-contact-label">Office address</div>
                    <div className="rep-detail-contact-value rep-detail-contact-static rep-detail-contact-address">
                      {data.office_address}
                    </div>
                  </div>
                </div>
              )}
              {data.mailing_address && (
                <div className="rep-detail-contact-row">
                  <MapPin size={16} aria-hidden="true" />
                  <div>
                    <div className="rep-detail-contact-label">Mailing address</div>
                    <div className="rep-detail-contact-value rep-detail-contact-static rep-detail-contact-address">
                      {data.mailing_address}
                    </div>
                  </div>
                </div>
              )}
            </section>

            <section className="rep-detail-actions" aria-label="External links">
              {data.profile_url && (
                <a href={data.profile_url} target="_blank" rel="noopener noreferrer"
                   className="rep-detail-action">
                  <ExternalLink size={14} aria-hidden="true" />
                  City Council profile
                </a>
              )}
              {data.office_hours_url && (
                <a href={data.office_hours_url} target="_blank" rel="noopener noreferrer"
                   className="rep-detail-action">
                  <Clock size={14} aria-hidden="true" />
                  Office hours
                </a>
              )}
            </section>

            {(data.committees || []).length > 0 && (
              <section className="rep-detail-committees" aria-label="Committee assignments">
                <h2 className="rep-detail-rail-h2">Committees</h2>
                <ul className="rep-detail-committee-list">
                  {data.committees.map(c => (
                    <li key={c.organization_id} className="rep-detail-committee-row">
                      <span className={`rep-detail-committee-role rep-detail-committee-role--${c.role.toLowerCase().replace(/[^a-z]/g, '-')}`}>
                        {c.role}
                      </span>
                      {c.source_url ? (
                        <a href={c.source_url} target="_blank" rel="noopener noreferrer"
                           className="rep-detail-committee-name">
                          {c.name}
                        </a>
                      ) : (
                        <span className="rep-detail-committee-name">{c.name}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {(data.staff || []).length > 0 && (
              <section className="rep-detail-staff" aria-label="Staff">
                <h2 className="rep-detail-rail-h2">Staff</h2>
                <ul className="rep-detail-staff-list">
                  {data.staff.map(s => (
                    <li key={s.email || s.name} className="rep-detail-staff-row">
                      <div className="rep-detail-staff-name">{s.name}</div>
                      {s.title && <div className="rep-detail-staff-title">{s.title}</div>}
                      {s.email && (
                        <a href={`mailto:${s.email}`} className="rep-detail-staff-email">
                          {s.email}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </header>

          <div className="rep-detail-main">
            {hasActivity && (
              <section className="rep-detail-vote-stats" aria-label="Lifetime activity totals — click a pill to filter the table below">
                <ul className="rep-detail-vote-breakdown">
                  {sponsorshipCounts.primary > 0 && (
                    <li>
                      <button
                        type="button"
                        onClick={() => togglePill('sponsorship', 'primary')}
                        aria-pressed={isPressed('sponsorship', 'primary')}
                        className={`rep-detail-vote-stat rep-detail-vote-stat--primary${isPressed('sponsorship', 'primary') ? ' rep-detail-vote-stat--active' : ''}`}
                      >
                        <span className="rep-detail-vote-stat-n">{sponsorshipCounts.primary}</span>
                        <span className="rep-detail-vote-stat-label">Primary sponsor</span>
                      </button>
                    </li>
                  )}
                  {sponsorshipCounts.cosponsor > 0 && (
                    <li>
                      <button
                        type="button"
                        onClick={() => togglePill('sponsorship', 'cosponsor')}
                        aria-pressed={isPressed('sponsorship', 'cosponsor')}
                        className={`rep-detail-vote-stat rep-detail-vote-stat--cosponsor${isPressed('sponsorship', 'cosponsor') ? ' rep-detail-vote-stat--active' : ''}`}
                      >
                        <span className="rep-detail-vote-stat-n">{sponsorshipCounts.cosponsor}</span>
                        <span className="rep-detail-vote-stat-label">Cosponsor</span>
                      </button>
                    </li>
                  )}
                  {VOTE_OPTION_ORDER.map(opt => {
                    const n = data.voting_history?.breakdown?.[opt] || 0
                    if (!n) return null
                    return (
                      <li key={opt}>
                        <button
                          type="button"
                          onClick={() => togglePill('vote', opt)}
                          aria-pressed={isPressed('vote', opt)}
                          className={`rep-detail-vote-stat rep-detail-vote-stat--${optionSlug(opt)}${isPressed('vote', opt) ? ' rep-detail-vote-stat--active' : ''}`}
                        >
                          <span className="rep-detail-vote-stat-n">{n}</span>
                          <span className="rep-detail-vote-stat-label">{optionTitle(opt)}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {(data.legislation_involvement || []).length > 0 && (
              <section className="rep-detail-involvement" aria-labelledby="rep-involvement-h2">
                <h2 id="rep-involvement-h2" className="rep-detail-section-h2">
                  Legislation
                  <span className="rep-detail-section-count">
                    {' '}({data.legislation_involvement.length})
                  </span>
                </h2>
                <LegislationInvolvementTable
                  rows={data.legislation_involvement}
                  repName={data.name}
                  activeFilter={activeFilter}
                  onClearFilter={() => setActiveFilter(null)}
                />
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Phone, Mail, Printer, MapPin, ExternalLink, Clock } from 'lucide-react'
import NotFound from './NotFound'
import LegislationCard from './LegislationCard'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './RepDetail.css'

// Order in which option tallies appear in the breakdown row. Keys
// match `_OPTION_LABELS` on the API side. Display labels are taken
// from each row's `option_label` so the source of truth lives in one
// place (Python).
const VOTE_OPTION_ORDER = ['yes', 'no', 'abstain', 'absent', 'excused', 'not voting', 'other']

const optionSlug = (s) => s.replace(/\s+/g, '-')

export default function RepDetail() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)
  useDocumentTitle(data?.name)

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
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

  if (status === 404) return <NotFound />
  if (error) return (
    <div className="rep-detail-page"><div role="alert" className="rep-detail-container">Could not load: {error}</div></div>
  )
  if (!data) return (
    <div className="rep-detail-page"><div role="status" className="rep-detail-container">Loading…</div></div>
  )

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
            {(data.committees || []).length > 0 && (
              <section className="rep-detail-committees" aria-label="Committee assignments">
                <h2 className="rep-detail-section-h2">Committees</h2>
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

            {(data.sponsored_bills_total || 0) > 0 && (
              <section className="rep-detail-bills" aria-label="Bills sponsored">
                <h2 className="rep-detail-section-h2">
                  Bills sponsored
                  <span className="rep-detail-section-count">
                    {' '}({data.sponsored_bills_total})
                  </span>
                </h2>
                <div className="rep-detail-bill-list">
                  {data.sponsored_bills.map(bill => (
                    <LegislationCard key={bill.slug} bill={bill} />
                  ))}
                </div>
                {data.sponsored_bills_total > data.sponsored_bills.length && (
                  <Link
                    to={`/legislation?sponsor=${encodeURIComponent(data.name)}`}
                    className="rep-detail-bills-viewall"
                  >
                    View all {data.sponsored_bills_total} bills sponsored by {data.name} →
                  </Link>
                )}
              </section>
            )}

            {(data.voting_history?.total || 0) > 0 && (
              <section className="rep-detail-votes" aria-labelledby="rep-votes-h2">
                <h2 id="rep-votes-h2" className="rep-detail-section-h2">
                  Voting history
                  <span className="rep-detail-section-count">
                    {' '}({data.voting_history.total})
                  </span>
                </h2>
                <ul className="rep-detail-vote-breakdown" aria-label="Lifetime vote totals">
                  {VOTE_OPTION_ORDER.map(opt => {
                    const n = data.voting_history.breakdown[opt] || 0
                    if (!n) return null
                    return (
                      <li
                        key={opt}
                        className={`rep-detail-vote-stat rep-detail-vote-stat--${optionSlug(opt)}`}
                      >
                        <span className="rep-detail-vote-stat-n">{n}</span>
                        <span className="rep-detail-vote-stat-label">
                          {opt === 'not voting' ? 'Not voting'
                            : opt.charAt(0).toUpperCase() + opt.slice(1)}
                        </span>
                      </li>
                    )
                  })}
                </ul>
                <h3 className="rep-detail-vote-recent-h3">Recent votes</h3>
                <ol className="rep-detail-vote-list">
                  {data.voting_history.recent.map((v, i) => (
                    <li
                      key={`${v.bill.slug}-${v.date}-${i}`}
                      className="rep-detail-vote-row"
                    >
                      <div className="rep-detail-vote-meta">
                        <time className="rep-detail-vote-date" dateTime={v.date}>
                          {v.date}
                        </time>
                        <span
                          className={`rep-detail-vote-option rep-detail-vote-option--${optionSlug(v.option)}`}
                        >
                          {v.option_label}
                        </span>
                        <span
                          className={`rep-detail-vote-result rep-detail-vote-result--${v.result}`}
                        >
                          {v.result === 'pass' ? 'Passed' : 'Failed'}
                        </span>
                      </div>
                      <Link
                        to={`/legislation/${v.bill.slug}/`}
                        className="rep-detail-vote-bill"
                      >
                        <span className="rep-detail-vote-bill-id">{v.bill.identifier}</span>
                        {v.bill.title && (
                          <span className="rep-detail-vote-bill-title">{v.bill.title}</span>
                        )}
                      </Link>
                    </li>
                  ))}
                </ol>
                {data.voting_history.total > data.voting_history.recent.length && (
                  <p className="rep-detail-vote-truncated">
                    Showing the {data.voting_history.recent.length} most recent
                    {' '}of {data.voting_history.total} recorded votes.
                  </p>
                )}
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

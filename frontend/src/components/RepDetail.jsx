import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Phone, Mail, ExternalLink, Clock } from 'lucide-react'
import NotFound from './NotFound'
import LegislationCard from './LegislationCard'
import './RepDetail.css'

export default function RepDetail() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)

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
    <div className="rep-detail-page"><div className="rep-detail-container">Could not load: {error}</div></div>
  )
  if (!data) return (
    <div className="rep-detail-page"><div className="rep-detail-container">Loading…</div></div>
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

        <header className="rep-detail-header">
          <div className="rep-detail-eyebrow">{data.district}</div>
          <h1 className="rep-detail-h1">{data.name}</h1>
          {data.district_description && (
            <p className="rep-detail-sub">{data.district_description}</p>
          )}
        </header>

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
      </div>
    </div>
  )
}

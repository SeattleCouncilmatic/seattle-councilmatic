import { useEffect, useState } from 'react'
import { useParams, useLocation, Link } from 'react-router-dom'
import NotFound from './NotFound'
import './LegislationDetail.css'

const VARIANT_CLASSES = {
  yellow: 'tag--yellow',
  green:  'tag--green',
  red:    'tag--red',
  blue:   'tag--blue',
  gray:   'tag--gray',
}

function StatusTag({ label, variant }) {
  const cls = VARIANT_CLASSES[variant] || 'tag--gray'
  return <span className={`status-tag ${cls}`}>{label}</span>
}

function formatDate(isoString) {
  if (!isoString) return '—'
  const d = new Date(isoString + 'T00:00:00')
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}

function MediaIcon({ mediaType }) {
  if (mediaType === 'application/pdf') return <span className="doc-icon">PDF</span>
  if (mediaType?.includes('word')) return <span className="doc-icon doc-icon--word">DOC</span>
  return <span className="doc-icon doc-icon--generic">FILE</span>
}

// Render a section reference as either a Link (if the LLM-emitted number
// resolves to a real MunicipalCodeSection in the affected_sections list)
// or plain text (e.g. when the LLM emits a chapter like "23.32" or a
// section that doesn't exist in our DB).
function SmcSectionRef({ number, validSet }) {
  const trimmed = (number || '').trim()
  if (!trimmed) return null
  if (!validSet.has(trimmed)) {
    return <span className="leg-key-change-section-text">SMC {trimmed}</span>
  }
  const parts = trimmed.split('.')
  if (parts.length !== 3) {
    return <span className="leg-key-change-section-text">SMC {trimmed}</span>
  }
  const [title, chapter, section] = parts
  return (
    <Link
      to={`/municode/${title}/${chapter}/${section}`}
      className="leg-key-change-section-link"
    >
      SMC {trimmed} →
    </Link>
  )
}

export default function LegislationDetail() {
  const { slug } = useParams()
  const location = useLocation()
  // If we arrived via a card on the index page, the current search params
  // are stashed in location.state.backToSearch so the breadcrumb can return
  // to the exact filtered view. Direct deep links have no state and fall
  // back to a fresh /legislation.
  const legislationHref = location.state?.backToSearch
    ? `/legislation?${location.state.backToSearch}`
    : '/legislation'

  const [bill, setBill] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    fetch(`/api/legislation/${slug}/`)
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
        if (data) { setBill(data); setLoading(false) }
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [slug])

  if (loading)  return <div className="leg-detail-loading">Loading…</div>
  if (notFound) return <NotFound kind="legislation" />
  if (error)    return <div className="leg-detail-error">Could not load legislation: {error}</div>

  const primarySponsors = bill.sponsors.filter(s => s.primary)
  const coSponsors      = bill.sponsors.filter(s => !s.primary)
  const hasSummary = !!bill.llm_summary
  const hasKeyChanges = (bill.llm_summary?.key_changes?.length || 0) > 0
  const hasDocuments = bill.documents.length > 0
  const showRightCol = hasKeyChanges || hasDocuments

  return (
    <main className="leg-detail-page">
      <div className="leg-detail-container">

        {/* Breadcrumb */}
        <nav className="leg-detail-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="leg-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <Link to={legislationHref}>Legislation</Link>
          <span className="leg-detail-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="leg-detail-breadcrumb-current">{bill.identifier}</span>
        </nav>

        {/* Header */}
        <header className="leg-detail-header">
          <p className="leg-detail-identifier">{bill.identifier}</p>
          <h1 className="leg-detail-title">{bill.title}</h1>
          <div className="leg-detail-meta-row">
            <StatusTag label={bill.status} variant={bill.status_variant} />
            {bill.committee && (
              <span className="leg-detail-meta-chip">{bill.committee}</span>
            )}
            {bill.bill_type && (
              <span className="leg-detail-meta-chip leg-detail-meta-chip--type">{bill.bill_type}</span>
            )}
          </div>
        </header>

        <div className={`leg-detail-body${
          hasSummary ? ' leg-detail-body--has-summary' : ''
        }${
          showRightCol ? ' leg-detail-body--has-rightcol' : ''
        }`}>

          {/* Left column: reference info — Details, Sponsors, Documents,
              and Action history. The right column(s) carry the LLM
              summary cards. */}
          <aside className="leg-detail-sidebar">

            <section className="leg-detail-section">
              <h2 className="leg-detail-section-title">Details</h2>
              <dl className="leg-detail-dl">
                <dt>Introduced</dt>
                <dd>{formatDate(bill.date_introduced)}</dd>
                <dt>Committee</dt>
                <dd>{bill.committee || '—'}</dd>
                <dt>Type</dt>
                <dd>{bill.bill_type || '—'}</dd>
                <dt>Last updated</dt>
                <dd>{bill.last_modified ? new Date(bill.last_modified).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'}</dd>
                {primarySponsors.length > 0 && (
                  <>
                    <dt>{primarySponsors.length === 1 ? 'Sponsor' : 'Sponsors'}</dt>
                    <dd>
                      <ul className="leg-detail-sponsor-list leg-detail-sponsor-list--inline">
                        {primarySponsors.map(s => (
                          <li key={s.name} className="leg-detail-sponsor leg-detail-sponsor--primary">
                            {s.name}
                          </li>
                        ))}
                      </ul>
                    </dd>
                  </>
                )}
                {coSponsors.length > 0 && (
                  <>
                    <dt>Co-sponsors</dt>
                    <dd>
                      <ul className="leg-detail-sponsor-list leg-detail-sponsor-list--inline">
                        {coSponsors.map(s => (
                          <li key={s.name} className="leg-detail-sponsor">
                            {s.name}
                          </li>
                        ))}
                      </ul>
                    </dd>
                  </>
                )}
                {bill.legistar_id && (
                  <>
                    <dt>Legistar</dt>
                    <dd>
                      <a
                        href={`https://seattle.legistar.com/LegislationDetail.aspx?ID=${bill.legistar_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="leg-detail-external-link"
                      >
                        View on Legistar ↗
                      </a>
                    </dd>
                  </>
                )}
              </dl>
            </section>

            <section className="leg-detail-section leg-detail-main">
              <h2 className="leg-detail-section-title">Action history</h2>
              {bill.actions.length === 0 ? (
                <p className="leg-detail-empty">No recorded actions.</p>
              ) : (
                <ol className="leg-detail-timeline">
                  {[...bill.actions].reverse().map((action, i) => (
                    <li key={i} className="leg-detail-timeline-item">
                      <span className="leg-detail-timeline-dot" />
                      <div className="leg-detail-timeline-content">
                        <p className="leg-detail-timeline-desc">{action.description}</p>
                        <time className="leg-detail-timeline-date">{formatDate(action.date)}</time>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </aside>

          {/* Middle column: Plain-language summary */}
          {bill.llm_summary && (
            <article className="leg-detail-section leg-summary-card leg-card-summary">
              <h2 className="leg-detail-section-title">Plain-language summary</h2>
              {bill.llm_summary.summary && (
                <>
                  <p className="leg-summary-eyebrow">Summary</p>
                  {bill.llm_summary.summary.split('\n\n').map((para, i) => (
                    <p key={i} className="leg-summary-prose">{para}</p>
                  ))}
                </>
              )}
              {bill.llm_summary.impact_analysis && (
                <>
                  <p className="leg-summary-eyebrow">Impact</p>
                  {bill.llm_summary.impact_analysis.split('\n\n').map((para, i) => (
                    <p key={i} className="leg-summary-prose">{para}</p>
                  ))}
                </>
              )}
              {bill.llm_summary.model_version && (
                <p className="leg-summary-meta">Generated by {bill.llm_summary.model_version}</p>
              )}
            </article>
          )}

          {/* Right column: Key changes on top, Documents below. The
              wrapper itself is one grid child; renders only when there's
              content for it (key_changes or documents). */}
          {showRightCol && (
            <div className="leg-detail-right-col">

              {hasKeyChanges && (() => {
                const validSet = new Set(
                  (bill.llm_summary.affected_sections || []).map(s => s.section_number)
                )
                return (
                  <article className="leg-detail-section leg-summary-card leg-card-changes">
                    <h2 className="leg-detail-section-title">Key changes</h2>
                    <ol className="leg-key-changes">
                      {bill.llm_summary.key_changes.map((kc, i) => (
                        <li key={i} className="leg-key-change">
                          <h3 className="leg-key-change-title">{kc.title}</h3>
                          {kc.description && (
                            <p className="leg-key-change-desc">{kc.description}</p>
                          )}
                          {kc.affected_section && (
                            <p className="leg-key-change-section">
                              Affected: <SmcSectionRef number={kc.affected_section} validSet={validSet} />
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </article>
                )
              })()}

              {hasDocuments && (
                <section className="leg-detail-section">
                  <h2 className="leg-detail-section-title">Documents</h2>
                  <ul className="leg-detail-doc-list">
                    {bill.documents.map((doc, i) => (
                      <li key={i} className="leg-detail-doc-item">
                        <MediaIcon mediaType={doc.media_type} />
                        <a
                          href={doc.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="leg-detail-doc-link"
                        >
                          {doc.name}
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

            </div>
          )}

        </div>
      </div>
    </main>
  )
}

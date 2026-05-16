import { useState } from 'react'
import { Link } from 'react-router-dom'
import './EventSummaryCard.css'

const _DATE_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'long', day: 'numeric', year: 'numeric',
})

function formatGeneratedAt(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return _DATE_FMT.format(d)
}

function formatTimestamp(seconds) {
  if (seconds == null) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

// Detect council bill / resolution / ordinance identifiers (e.g.
// "CB 121181", "Res 32196") and replace them with internal Links
// resolved via the bill_refs map the API ships alongside the prose.
// Identifiers not in the map (or rare types we don't link) pass through
// as plain text.
const _BILL_REF_RE = /\b(?:CB|Res|Ord|CF) \d+\b/g

function linkifyBillRefs(text, billRefs) {
  if (!text) return null
  if (!billRefs || Object.keys(billRefs).length === 0) return text
  const parts = []
  let lastIdx = 0
  let key = 0
  _BILL_REF_RE.lastIndex = 0
  let match
  while ((match = _BILL_REF_RE.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index))
    }
    const identifier = match[0]
    const slug = billRefs[identifier]
    if (slug) {
      parts.push(
        <Link key={key++} to={`/legislation/${slug}/`} className="evt-summary-card-billref">
          {identifier}
        </Link>
      )
    } else {
      parts.push(identifier)
    }
    lastIdx = _BILL_REF_RE.lastIndex
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx))
  return parts
}

export default function EventSummaryCard({ summary }) {
  const [itemsOpen, setItemsOpen] = useState(false)
  if (!summary?.overview) return null

  const overviewParas = summary.overview.split(/\n\n+/).filter(Boolean)
  const items = summary.item_summaries || []
  const billRefs = summary.bill_refs || {}
  const videoUrl = summary.video_url || ''
  const generatedDate = formatGeneratedAt(summary.generated_at)

  return (
    <section
      className="evt-summary-card"
      aria-labelledby="evt-summary-card-h2"
    >
      <h2 id="evt-summary-card-h2" className="evt-summary-card-h2">
        Meeting overview
      </h2>
      <div className="evt-summary-card-body">
        {overviewParas.map((p, i) => (
          <p key={i} className="evt-summary-card-p">
            {linkifyBillRefs(p, billRefs)}
          </p>
        ))}
      </div>

      {videoUrl && (
        <p className="evt-summary-card-watch">
          <a href={videoUrl} target="_blank" rel="noopener noreferrer">
            Watch the full meeting on Seattle Channel
          </a>
        </p>
      )}

      {items.length > 0 && (
        <details
          className="evt-summary-card-items"
          open={itemsOpen}
          onToggle={(e) => setItemsOpen(e.currentTarget.open)}
        >
          <summary className="evt-summary-card-items-toggle">
            {itemsOpen ? 'Hide' : 'Show'} per-item summaries ({items.length})
          </summary>
          <ol className="evt-summary-card-item-list">
            {items.map((it, i) => {
              const ts = formatTimestamp(it.start_seconds)
              return (
                <li key={i} className="evt-summary-card-item">
                  <div className="evt-summary-card-item-header">
                    <span className="evt-summary-card-item-label">
                      {linkifyBillRefs(it.label, billRefs)}
                    </span>
                    {it.start_seconds != null && (
                      videoUrl ? (
                        <a
                          href={`${videoUrl}#t=${it.start_seconds}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="evt-summary-card-item-ts evt-summary-card-item-ts--link"
                          title={`Jump to ${ts} in the meeting recording`}
                        >
                          {ts}
                        </a>
                      ) : (
                        <span className="evt-summary-card-item-ts">{ts}</span>
                      )
                    )}
                  </div>
                  <p className="evt-summary-card-item-summary">
                    {linkifyBillRefs(it.summary, billRefs)}
                  </p>
                </li>
              )
            })}
          </ol>
        </details>
      )}

      <footer className="evt-summary-card-footer">
        AI-generated synthesis of the captioned meeting transcript and
        agenda.
        {generatedDate && (
          <> Generated {generatedDate}.</>
        )}
      </footer>
    </section>
  )
}

import './CommitteeSummaryCard.css'

const _DATE_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'long', day: 'numeric', year: 'numeric',
})

function formatGeneratedAt(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return _DATE_FMT.format(d)
}

export default function CommitteeSummaryCard({ summary }) {
  if (!summary) return null
  const scope = summary.scope || []
  const activity = summary.recent_activity || []
  const hasBullets = scope.length > 0 || activity.length > 0 || !!summary.scope_intro
  // Fallback for summaries generated before the bulleted format — they
  // only have `text` (paragraphs).
  const paragraphs = !hasBullets && summary.text
    ? summary.text.split(/\n\n+/).filter(Boolean)
    : []
  if (!hasBullets && paragraphs.length === 0) return null

  const generatedDate = formatGeneratedAt(summary.generated_at)

  return (
    <section className="cmte-summary-card" aria-labelledby="cmte-summary-card-h2">
      <h2 id="cmte-summary-card-h2" className="cmte-summary-card-h2">Overview</h2>

      {hasBullets ? (
        <div className="cmte-summary-card-body">
          {(summary.scope_intro || scope.length > 0) && (
            <>
              <h3 className="cmte-summary-card-h3">Scope</h3>
              {summary.scope_intro && (
                <p className="cmte-summary-card-p">{summary.scope_intro}</p>
              )}
              {scope.length > 0 && (
                <ul className="cmte-summary-card-list">
                  {scope.map((b, i) => <li key={i}>{b}</li>)}
                </ul>
              )}
            </>
          )}
          {activity.length > 0 && (
            <>
              <h3 className="cmte-summary-card-h3">Recent activity</h3>
              <ul className="cmte-summary-card-list">
                {activity.map((b, i) => <li key={i}>{b}</li>)}
              </ul>
            </>
          )}
        </div>
      ) : (
        <div className="cmte-summary-card-body">
          {paragraphs.map((p, i) => (
            <p key={i} className="cmte-summary-card-p">{p}</p>
          ))}
        </div>
      )}

      <footer className="cmte-summary-card-footer">
        AI-generated overview of this committee&rsquo;s scope and recent
        activity, drawn from its seattle.gov page, meetings, and legislation.
        {generatedDate && (
          <> Generated {generatedDate}.</>
        )}
      </footer>
    </section>
  )
}

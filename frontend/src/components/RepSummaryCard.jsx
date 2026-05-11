import './RepSummaryCard.css'

const _DATE_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'long', day: 'numeric', year: 'numeric',
})

function formatGeneratedAt(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return _DATE_FMT.format(d)
}

export default function RepSummaryCard({ summary, repName }) {
  if (!summary?.text) return null
  const paragraphs = summary.text.split(/\n\n+/).filter(Boolean)
  const generatedDate = formatGeneratedAt(summary.generated_at)
  return (
    <section
      className="rep-summary-card"
      aria-labelledby="rep-summary-card-h2"
    >
      <h2 id="rep-summary-card-h2" className="rep-summary-card-h2">
        Overview
      </h2>
      <div className="rep-summary-card-body">
        {paragraphs.map((p, i) => (
          <p key={i} className="rep-summary-card-p">{p}</p>
        ))}
      </div>
      <footer className="rep-summary-card-footer">
        AI-generated synthesis of {repName}&rsquo;s public sponsorship,
        voting record, and biographical context.
        {generatedDate && (
          <> Generated {generatedDate}.</>
        )}
      </footer>
    </section>
  )
}

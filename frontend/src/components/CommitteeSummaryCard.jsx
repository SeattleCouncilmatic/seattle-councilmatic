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
  if (!summary?.text) return null
  const paragraphs = summary.text.split(/\n\n+/).filter(Boolean)
  const generatedDate = formatGeneratedAt(summary.generated_at)
  return (
    <section
      className="cmte-summary-card"
      aria-labelledby="cmte-summary-card-h2"
    >
      <h2 id="cmte-summary-card-h2" className="cmte-summary-card-h2">
        Overview
      </h2>
      <div className="cmte-summary-card-body">
        {paragraphs.map((p, i) => (
          <p key={i} className="cmte-summary-card-p">{p}</p>
        ))}
      </div>
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

import { Link } from 'react-router-dom'
import './RollCall.css'

// Order in which option groupings appear within each event card.
// Keys are pupa's standard vote options as set by `seattle/vote_events.py`.
const OPTION_ORDER = ['yes', 'no', 'abstain', 'absent', 'excused', 'not voting', 'other']

const OPTION_LABELS = {
  'yes':         'Yes',
  'no':          'No',
  'abstain':     'Abstain',
  'absent':      'Absent',
  'excused':     'Excused',
  'not voting':  'Not voting',
  'other':       'Other',
}

const optionSlug = (s) => s.replace(/\s+/g, '-')

function formatDate(isoDate) {
  if (!isoDate) return ''
  const d = new Date(isoDate + 'T00:00:00')
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}

// Each councilmember's name. Renders as a `<Link>` to /reps/<slug>/
// when the API resolved a current-member slug; otherwise plain text
// (former members without a live profile page, historical members
// not in our Person table at all).
function VoterName({ entry }) {
  if (entry.slug) {
    return (
      <Link to={`/reps/${entry.slug}/`} className="rollcall-voter-link">
        {entry.name}
      </Link>
    )
  }
  return <span className="rollcall-voter-text">{entry.name}</span>
}

function tallyText(counts) {
  // Pretty "8–0" / "5–2 (1 abstain)" style aggregate. Yes/no carry
  // the headline; abstain/absent/etc. get a parenthesized footer
  // when present so the headline stays readable on close votes.
  const yes = counts.yes || 0
  const no = counts.no || 0
  const extras = []
  for (const opt of ['abstain', 'absent', 'excused', 'not voting', 'other']) {
    const n = counts[opt] || 0
    if (n) extras.push(`${n} ${OPTION_LABELS[opt].toLowerCase()}`)
  }
  const head = `${yes}–${no}` // en-dash
  return extras.length ? `${head} (${extras.join(', ')})` : head
}

function VoteEventCard({ event }) {
  const resultClass = event.result === 'pass'
    ? 'rollcall-result rollcall-result--pass'
    : 'rollcall-result rollcall-result--fail'
  const optionsToShow = OPTION_ORDER.filter(opt => (event.votes_by_option[opt] || []).length > 0)

  return (
    <article className="rollcall-event">
      <header className="rollcall-event-header">
        <div className="rollcall-event-where">
          <span className="rollcall-event-body">{event.body_name || 'Council'}</span>
          {event.is_council && (
            <span className="rollcall-event-tag" aria-hidden="true">Full council</span>
          )}
        </div>
        <time className="rollcall-event-date" dateTime={event.date}>
          {formatDate(event.date)}
        </time>
      </header>

      <p className="rollcall-event-tally">
        <span className={resultClass}>
          {event.result === 'pass' ? 'Passed' : 'Failed'}
        </span>{' '}
        <span className="rollcall-event-counts">{tallyText(event.counts)}</span>
      </p>

      <dl className="rollcall-options">
        {optionsToShow.map(opt => {
          const voters = event.votes_by_option[opt]
          return (
            <div key={opt} className={`rollcall-option rollcall-option--${optionSlug(opt)}`}>
              <dt className="rollcall-option-label">
                <span className={`rollcall-option-chip rollcall-option-chip--${optionSlug(opt)}`}>
                  {OPTION_LABELS[opt] || opt}
                </span>
                <span className="rollcall-option-count">({voters.length})</span>
              </dt>
              <dd className="rollcall-option-voters">
                {voters.map((v, i) => (
                  <span key={`${v.slug || v.name}-${i}`} className="rollcall-voter">
                    <VoterName entry={v} />
                    {i < voters.length - 1 && <span className="rollcall-voter-sep" aria-hidden="true">, </span>}
                  </span>
                ))}
              </dd>
            </div>
          )
        })}
      </dl>

      {event.motion_text && (
        <p className="rollcall-event-motion">
          <span className="rollcall-motion-label">Motion: </span>
          {event.motion_text}
        </p>
      )}
    </article>
  )
}

export default function RollCall({ events }) {
  if (!events || events.length === 0) return null
  return (
    <section className="rollcall-section" aria-labelledby="rollcall-h2">
      <h2 id="rollcall-h2" className="rollcall-section-title">
        Roll call votes
        <span className="rollcall-section-count">
          {' '}({events.length} {events.length === 1 ? 'vote' : 'votes'})
        </span>
      </h2>
      <div className="rollcall-event-list">
        {events.map((ev, i) => (
          <VoteEventCard key={`${ev.date}-${i}`} event={ev} />
        ))}
      </div>
    </section>
  )
}

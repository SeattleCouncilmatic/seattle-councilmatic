import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail } from 'lucide-react'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './SubscribeForm.css'

// Multi-step subscribe form for personalized email digests (#231).
// Steps: email + cadence → issue areas → reps/district → review.
// Rendered standalone at /digests/subscribe and embedded on the homepage.
//
// Double opt-in: submitting only triggers a verification email; the
// subscription activates when that link is clicked, so a typo'd or
// malicious signup never emails anyone twice.

const TOTAL_STEPS = 4

export default function SubscribeForm({ embedded = false }) {
  // Heading levels shift with context (AUDIT_FINDINGS: one h1 per page,
  // no level skips): standalone page owns the h1; the homepage embed
  // slots under LegislationHero's h1 as an h2 section.
  const H = embedded ? 'h2' : 'h1'
  const SubH = embedded ? 'h3' : 'h2'
  const [options, setOptions] = useState(null)
  const [step, setStep] = useState(0)
  const [email, setEmail] = useState('')
  const [weeklyEnabled, setWeeklyEnabled] = useState(true)
  const [dailyEnabled, setDailyEnabled] = useState(false)
  const [issueAreas, setIssueAreas] = useState([])
  const [repIds, setRepIds] = useState([])
  const [districtId, setDistrictId] = useState('')
  const [honeypot, setHoneypot] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  const uid = useId()
  const headingRef = useRef(null)
  const mounted = useRef(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/digests/options')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(data => { if (!cancelled) setOptions(data) })
      .catch(() => { if (!cancelled) setOptions({ issue_areas: [], reps: [], districts: [] }) })
    return () => { cancelled = true }
  }, [])

  // Keyboard/SR users: on step change, move focus to the new step's
  // heading so the transition is announced and Tab starts in the right
  // place. Skipped on initial mount (don't steal homepage focus).
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return }
    headingRef.current?.focus()
  }, [step, done])

  const toggle = (list, setList, value) =>
    setList(list.includes(value) ? list.filter(v => v !== value) : [...list, value])

  const next = () => {
    if (step === 0) {
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
        setError('Please enter a valid email address.')
        return
      }
      if (!weeklyEnabled && !dailyEnabled) {
        setError('Pick at least one cadence — weekly or daily.')
        return
      }
    }
    setError(null)
    setStep(s => Math.min(s + 1, TOTAL_STEPS - 1))
  }

  const back = () => { setError(null); setStep(s => Math.max(s - 1, 0)) }

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch('/api/digests/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          weekly_enabled: weeklyEnabled,
          daily_enabled: dailyEnabled,
          issue_areas: issueAreas,
          followed_rep_ids: repIds,
          district_id: districtId ? Number(districtId) : null,
          website: honeypot,
        }),
      })
      if (r.status === 202) {
        setDone(true)
      } else {
        const data = await r.json().catch(() => ({}))
        setError(data.error || `Something went wrong (HTTP ${r.status}). Please try again.`)
      }
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const districtName = districtId
    ? options?.districts.find(d => String(d.id) === String(districtId))?.name
    : null

  return (
    <section
      className={`subscribe-form${embedded ? ' subscribe-form--embedded' : ''}`}
      aria-labelledby={`${uid}-title`}
    >
      <div className="sf-inner">
        <header className="sf-header">
          <H className="sf-title" id={`${uid}-title`}>
            <Mail className="sf-title-icon" size={26} aria-hidden="true" />
            Get council updates by email
          </H>
          <p className="sf-subtitle">
            A personalized digest of Seattle City Council activity — only the
            topics, councilmembers, and district you choose. Free, no account,
            unsubscribe anytime.
          </p>
          <p className="sf-muted">
            Already subscribed?{' '}
            <Link to="/digests/preferences">Manage your preferences</Link>.
          </p>
        </header>

        {done ? (
          <div className="sf-done" role="status">
            <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
              Check your inbox
            </SubH>
            <p>
              We sent a confirmation link to <strong>{email.trim()}</strong>.
              Your digest starts once you click it — nothing is sent until then.
            </p>
          </div>
        ) : (
          <form onSubmit={e => { e.preventDefault(); step === TOTAL_STEPS - 1 ? submit() : next() }}>
            <p className="sf-step-count">Step {step + 1} of {TOTAL_STEPS}</p>

            {/* Honeypot — hidden from real users, filled by bots. */}
            <div className="sf-hp" aria-hidden="true">
              <label htmlFor={`${uid}-website`}>Website</label>
              <input
                id={`${uid}-website`}
                type="text"
                name="website"
                tabIndex={-1}
                autoComplete="off"
                value={honeypot}
                onChange={e => setHoneypot(e.target.value)}
              />
            </div>

            {step === 0 && (
              <div>
                <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                  Where should we send it?
                </SubH>
                <label className="sf-label" htmlFor={`${uid}-email`}>Email address</label>
                <input
                  className="sf-input"
                  id={`${uid}-email`}
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  aria-describedby={error ? `${uid}-error` : undefined}
                />
                <fieldset className="sf-fieldset">
                  <legend className="sf-legend">How often?</legend>
                  <label className="sf-check">
                    <input
                      type="checkbox"
                      checked={weeklyEnabled}
                      onChange={e => setWeeklyEnabled(e.target.checked)}
                    />
                    <span>Weekly summary <span className="sf-muted">(Sunday mornings)</span></span>
                  </label>
                  <label className="sf-check">
                    <input
                      type="checkbox"
                      checked={dailyEnabled}
                      onChange={e => setDailyEnabled(e.target.checked)}
                    />
                    <span>Daily, when there's news matching your interests</span>
                  </label>
                </fieldset>
              </div>
            )}

            {step === 1 && (
              <fieldset className="sf-fieldset">
                <legend className="sf-legend">
                  <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                    Which topics interest you?
                  </SubH>
                </legend>
                <p className="sf-muted">
                  Optional — pick any. Leave everything unchecked to hear about
                  it all through your other selections.
                </p>
                <div className="sf-checkbox-grid">
                  {(options?.issue_areas ?? []).map(tag => (
                    <label className="sf-check" key={tag}>
                      <input
                        type="checkbox"
                        checked={issueAreas.includes(tag)}
                        onChange={() => toggle(issueAreas, setIssueAreas, tag)}
                      />
                      <span>{tag}</span>
                    </label>
                  ))}
                </div>
                {options && options.issue_areas.length === 0 && (
                  <p className="sf-muted">Topic list is unavailable right now — you can skip this step.</p>
                )}
              </fieldset>
            )}

            {step === 2 && (
              <div>
                <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                  Who represents you?
                </SubH>
                <fieldset className="sf-fieldset">
                  <legend className="sf-legend">Councilmembers to follow (optional)</legend>
                  <div className="sf-checkbox-grid">
                    {(options?.reps ?? []).map(rep => (
                      <label className="sf-check" key={rep.id}>
                        <input
                          type="checkbox"
                          checked={repIds.includes(rep.id)}
                          onChange={() => toggle(repIds, setRepIds, rep.id)}
                        />
                        <span>{rep.name} <span className="sf-muted">({rep.seat})</span></span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="sf-label" htmlFor={`${uid}-district`}>
                  Your council district (optional)
                </label>
                <select
                  className="sf-input"
                  id={`${uid}-district`}
                  value={districtId}
                  onChange={e => setDistrictId(e.target.value)}
                >
                  <option value="">No district preference</option>
                  {(options?.districts ?? []).map(d => (
                    <option key={d.id} value={d.id}>
                      {d.name}{d.description ? ` — ${d.description}` : ''}
                    </option>
                  ))}
                </select>
                <p className="sf-muted">
                  Not sure which district?{' '}
                  <Link to="/reps">Look up your address on the council map</Link>.
                </p>
              </div>
            )}

            {step === 3 && (
              <div>
                <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                  Ready to go?
                </SubH>
                <dl className="sf-review">
                  <div><dt>Email</dt><dd>{email.trim()}</dd></div>
                  <div>
                    <dt>Cadence</dt>
                    <dd>{[weeklyEnabled && 'Weekly', dailyEnabled && 'Daily when there’s news'].filter(Boolean).join(' + ')}</dd>
                  </div>
                  <div>
                    <dt>Topics</dt>
                    <dd>{issueAreas.length ? issueAreas.join(', ') : 'No topic filter'}</dd>
                  </div>
                  <div>
                    <dt>Following</dt>
                    <dd>
                      {repIds.length
                        ? (options?.reps ?? []).filter(r => repIds.includes(r.id)).map(r => r.name).join(', ')
                        : 'No councilmembers selected'}
                    </dd>
                  </div>
                  <div><dt>District</dt><dd>{districtName || 'No district preference'}</dd></div>
                </dl>
                <p className="sf-muted">
                  We'll email a confirmation link first — nothing is sent until
                  you click it. Every digest includes one-click unsubscribe.
                  We never share your address.
                </p>
              </div>
            )}

            {error && (
              <p className="sf-error" id={`${uid}-error`} role="alert">{error}</p>
            )}

            <div className="sf-nav">
              {step > 0 && (
                <button type="button" className="sf-btn sf-btn--secondary" onClick={back}>
                  Back
                </button>
              )}
              <button type="submit" className="sf-btn" disabled={submitting}>
                {step === TOTAL_STEPS - 1
                  ? (submitting ? 'Subscribing…' : 'Subscribe')
                  : 'Continue'}
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  )
}

// Standalone page wrapper for the /digests/subscribe route.
export function SubscribePage() {
  useDocumentTitle('Subscribe to email digests')
  return (
    <div className="subscribe-page">
      <SubscribeForm />
    </div>
  )
}

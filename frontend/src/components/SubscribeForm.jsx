import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail } from 'lucide-react'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './SubscribeForm.css'

// Multi-step subscribe form for personalized email digests (#231).
// Steps: email + cadence → district (required) → topics → review.
// The district is the personalization anchor — it maps the subscriber to
// their representatives (district seat + the citywide members) server-side,
// so there's no councilmember picker. Rendered standalone at
// /digests/subscribe and embedded on the homepage.
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
  const [issueAreas, setIssueAreas] = useState([])
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
      // Fail open on a fetch error (signup_open: true): the picker lists
      // degrade to empty but the form still works, and the server-side
      // signup gate is what actually enforces closed signups.
      .catch(() => { if (!cancelled) setOptions({ signup_open: true, issue_areas: [], districts: [] }) })
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
      if (!weeklyEnabled) {
        setError('Weekly delivery is the only cadence available right now — keep it checked to subscribe.')
        return
      }
    }
    if (step === 1 && !districtId) {
      setError('Please choose your council district — it’s how we match council activity to you.')
      return
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
          issue_areas: issueAreas,
          district_id: Number(districtId),
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

  // Signups closed (the admin gate — the pre-launch state on prod):
  // the homepage embed disappears entirely (also while options load, so a
  // closed prod homepage never flashes the form); the standalone page
  // explains. The footer link stays, which is fine — it just lands here.
  const signupClosed = options && options.signup_open === false
  if (embedded && (!options || signupClosed)) return null

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
            A personalized digest of Seattle City Council activity — your
            district&rsquo;s representatives plus the topics you choose. Free,
            no account, unsubscribe anytime.
          </p>
          <p className="sf-muted">
            Already subscribed?{' '}
            <Link to="/digests/preferences">Manage your preferences</Link>.
          </p>
        </header>

        {signupClosed ? (
          <div className="sf-done" role="status">
            <SubH className="sf-step-title" tabIndex={-1}>
              Coming soon
            </SubH>
            <p>
              Digest signups aren't open yet — we're still testing the first
              issues. Check back soon.
            </p>
          </div>
        ) : done ? (
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
                  {/* Daily is built but not rolled out — disabled with
                      explicit colors (AUDIT_FINDINGS: never opacity-only). */}
                  <label className="sf-check sf-check--disabled">
                    <input type="checkbox" checked={false} disabled readOnly />
                    <span>
                      Daily, when there's news matching your interests{' '}
                      <span className="sf-coming-soon">(coming soon)</span>
                    </span>
                  </label>
                </fieldset>
              </div>
            )}

            {step === 1 && (
              <div>
                <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                  Which district do you live in?
                </SubH>
                <p className="sf-muted">
                  Your district connects you to your representatives — the
                  district&rsquo;s councilmember plus the two citywide
                  members — so their legislation and committee work reaches
                  your digest.
                </p>
                <label className="sf-label" htmlFor={`${uid}-district`}>
                  Your council district
                </label>
                <select
                  className="sf-input"
                  id={`${uid}-district`}
                  required
                  value={districtId}
                  onChange={e => setDistrictId(e.target.value)}
                  aria-describedby={error ? `${uid}-error` : undefined}
                >
                  <option value="">Choose your district…</option>
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

            {step === 2 && (
              <fieldset className="sf-fieldset">
                <legend className="sf-legend">
                  <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                    Which topics interest you?
                  </SubH>
                </legend>
                <p className="sf-muted">
                  Optional — pick any. Your representatives&rsquo; activity is
                  included either way; topics widen the net to the whole
                  council.
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

            {step === 3 && (
              <div>
                <SubH className="sf-step-title" tabIndex={-1} ref={headingRef}>
                  Ready to go?
                </SubH>
                <dl className="sf-review">
                  <div><dt>Email</dt><dd>{email.trim()}</dd></div>
                  <div><dt>Cadence</dt><dd>Weekly</dd></div>
                  <div><dt>District</dt><dd>{districtName}</dd></div>
                  <div>
                    <dt>Topics</dt>
                    <dd>{issueAreas.length ? issueAreas.join(', ') : 'No topic filter — just your representatives’ activity'}</dd>
                  </div>
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

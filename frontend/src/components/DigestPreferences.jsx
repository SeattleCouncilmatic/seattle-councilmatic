import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Settings } from 'lucide-react'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './DigestPreferences.css'

// Preferences editor for existing digest subscribers (#231). Reached via
// the "manage" link in digest emails: Django's /digests/manage endpoint
// verifies the HMAC token, sets a short-lived session cookie, and
// redirects here — so this page talks to /api/digests/preferences with
// session auth and never sees the token itself.

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

export default function DigestPreferences() {
  useDocumentTitle('Email digest preferences')
  const [options, setOptions] = useState(null)
  const [prefs, setPrefs] = useState(null)     // server payload
  const [authError, setAuthError] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [statusMsg, setStatusMsg] = useState(null)   // {kind: 'ok'|'error', text}
  // Request-a-manage-link form (shown when unauthenticated).
  const [requestEmail, setRequestEmail] = useState('')
  const [requestState, setRequestState] = useState('idle')  // idle | sending | sent
  const [requestError, setRequestError] = useState(null)
  const uid = useId()
  const statusRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetch('/api/digests/preferences').then(r => {
        if (r.status === 401) throw new Error('auth')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      }),
      fetch('/api/digests/options').then(r => (r.ok ? r.json() : { issue_areas: [], districts: [] })),
    ])
      .then(([prefsData, optionsData]) => {
        if (cancelled) return
        setPrefs(prefsData)
        setOptions(optionsData)
      })
      .catch(err => {
        if (cancelled) return
        if (err.message === 'auth') setAuthError(true)
        else setLoadError(true)
      })
    return () => { cancelled = true }
  }, [])

  const update = patch => setPrefs(p => ({ ...p, ...patch }))

  const toggleInList = (key, value) =>
    setPrefs(p => ({
      ...p,
      [key]: p[key].includes(value) ? p[key].filter(v => v !== value) : [...p[key], value],
    }))

  const save = async e => {
    e.preventDefault()
    if (!prefs.weekly_enabled) {
      setStatusMsg({ kind: 'error', text: 'Weekly delivery is the only cadence available right now. To stop all email, use the unsubscribe link below.' })
      return
    }
    if (!prefs.district_id) {
      setStatusMsg({ kind: 'error', text: 'Please choose your council district — it’s how we match council activity to you.' })
      return
    }
    setSaving(true)
    setStatusMsg(null)
    try {
      const r = await fetch('/api/digests/preferences', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
          weekly_enabled: prefs.weekly_enabled,
          issue_areas: prefs.issue_areas,
          district_id: prefs.district_id,
        }),
      })
      if (r.status === 401) { setAuthError(true); setSessionExpired(true); return }
      const data = await r.json().catch(() => ({}))
      if (r.ok) {
        setPrefs(data)
        setStatusMsg({ kind: 'ok', text: 'Preferences saved.' })
      } else {
        setStatusMsg({ kind: 'error', text: data.error || `Save failed (HTTP ${r.status}).` })
      }
    } catch {
      setStatusMsg({ kind: 'error', text: 'Could not reach the server. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  const requestManageLink = async e => {
    e.preventDefault()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(requestEmail.trim())) {
      setRequestError('Please enter a valid email address.')
      return
    }
    setRequestState('sending')
    setRequestError(null)
    try {
      const r = await fetch('/api/digests/manage-link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: requestEmail.trim() }),
      })
      if (r.status === 202) {
        setRequestState('sent')
      } else {
        const data = await r.json().catch(() => ({}))
        setRequestState('idle')
        setRequestError(data.error || `Something went wrong (HTTP ${r.status}). Please try again.`)
      }
    } catch {
      setRequestState('idle')
      setRequestError('Could not reach the server. Please try again.')
    }
  }

  if (authError) {
    return (
      <div className="digest-prefs">
        <div className="dp-inner">
          <h1 className="dp-title">Email digest preferences</h1>
          <div className="dp-notice">
            {requestState === 'sent' ? (
              <p role="status">
                If <strong>{requestEmail.trim()}</strong> is subscribed, a
                manage link is on its way — check your inbox.
              </p>
            ) : (
              <>
                <p role="status">
                  {sessionExpired
                    ? 'Your session expired. Enter your email and we’ll send a fresh manage link.'
                    : 'This page needs a manage link — enter your subscribed email and we’ll send you one (no password needed; the link signs you in for an hour).'}
                </p>
                <form onSubmit={requestManageLink} className="dp-request-form">
                  <label className="dp-legend" htmlFor={`${uid}-request-email`}>
                    Email address
                  </label>
                  <input
                    className="dp-input"
                    id={`${uid}-request-email`}
                    type="email"
                    autoComplete="email"
                    required
                    value={requestEmail}
                    onChange={e2 => setRequestEmail(e2.target.value)}
                    aria-describedby={requestError ? `${uid}-request-error` : undefined}
                  />
                  {requestError && (
                    <p className="dp-error" id={`${uid}-request-error`} role="alert">
                      {requestError}
                    </p>
                  )}
                  <div className="dp-actions">
                    <button type="submit" className="dp-btn" disabled={requestState === 'sending'}>
                      {requestState === 'sending' ? 'Sending…' : 'Email me a manage link'}
                    </button>
                  </div>
                </form>
                <p className="dp-muted">
                  Not subscribed yet? <Link to="/digests/subscribe">Sign up for digests</Link>.
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="digest-prefs">
        <div className="dp-inner">
          <h1 className="dp-title">Email digest preferences</h1>
          <p className="dp-error" role="alert">Could not load your preferences. Please try again.</p>
        </div>
      </div>
    )
  }

  if (!prefs || !options) {
    return (
      <div className="digest-prefs">
        <div className="dp-inner">
          <h1 className="dp-title">Email digest preferences</h1>
          <p role="status">Loading your preferences…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="digest-prefs">
      <div className="dp-inner">
        <header className="dp-header">
          <h1 className="dp-title">
            <Settings className="dp-title-icon" size={26} aria-hidden="true" />
            Email digest preferences
          </h1>
          <p className="dp-subtitle">
            Digests go to <strong>{prefs.email_masked}</strong>.
          </p>
        </header>

        <form onSubmit={save}>
          <fieldset className="dp-fieldset">
            <legend className="dp-legend">Cadence</legend>
            <label className="dp-check">
              <input
                type="checkbox"
                checked={prefs.weekly_enabled}
                onChange={e => update({ weekly_enabled: e.target.checked })}
              />
              <span>Weekly summary <span className="dp-muted">(Sunday mornings)</span></span>
            </label>
            {/* Daily is built but not rolled out — disabled with explicit
                colors (AUDIT_FINDINGS: never opacity-only). */}
            <label className="dp-check dp-check--disabled">
              <input type="checkbox" checked={false} disabled readOnly />
              <span>
                Daily, when there's news matching your interests{' '}
                <span className="dp-coming-soon">(coming soon)</span>
              </span>
            </label>
          </fieldset>

          <div className="dp-field">
            <label className="dp-legend" htmlFor={`${uid}-district`}>Your council district</label>
            <p className="dp-muted">
              Your district connects you to your representatives — the
              district&rsquo;s councilmember plus the two citywide members.
            </p>
            <select
              className="dp-input"
              id={`${uid}-district`}
              required
              value={prefs.district_id ?? ''}
              onChange={e => update({ district_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">Choose your district…</option>
              {options.districts.map(d => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.description ? ` — ${d.description}` : ''}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="dp-fieldset">
            <legend className="dp-legend">Topics</legend>
            <p className="dp-muted">
              Optional — your representatives&rsquo; activity is included
              either way; topics widen the net to the whole council.
            </p>
            <div className="dp-checkbox-grid">
              {options.issue_areas.map(tag => (
                <label className="dp-check" key={tag}>
                  <input
                    type="checkbox"
                    checked={prefs.issue_areas.includes(tag)}
                    onChange={() => toggleInList('issue_areas', tag)}
                  />
                  <span>{tag}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {statusMsg && (
            <p
              className={statusMsg.kind === 'ok' ? 'dp-status-ok' : 'dp-error'}
              role={statusMsg.kind === 'ok' ? 'status' : 'alert'}
              ref={statusRef}
            >
              {statusMsg.text}
            </p>
          )}

          <div className="dp-actions">
            <button type="submit" className="dp-btn" disabled={saving}>
              {saving ? 'Saving…' : 'Save preferences'}
            </button>
          </div>
        </form>

        <hr className="dp-divider" />
        <p className="dp-muted">
          Want out entirely?{' '}
          <a href={prefs.unsubscribe_url}>Unsubscribe from all digest email</a>
          {' '}— takes effect immediately, and you can delete your data on the
          same page.
        </p>
      </div>
    </div>
  )
}

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
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [statusMsg, setStatusMsg] = useState(null)   // {kind: 'ok'|'error', text}
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
      fetch('/api/digests/options').then(r => (r.ok ? r.json() : { issue_areas: [], reps: [], districts: [] })),
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
    if (!prefs.weekly_enabled && !prefs.daily_enabled) {
      setStatusMsg({ kind: 'error', text: 'Pick at least one cadence — weekly or daily. To stop all email, use the unsubscribe link below.' })
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
          daily_enabled: prefs.daily_enabled,
          issue_areas: prefs.issue_areas,
          followed_rep_ids: prefs.followed_rep_ids,
          followed_bill_ids: prefs.followed_bills.map(b => b.id),
          district_id: prefs.district_id,
        }),
      })
      if (r.status === 401) { setAuthError(true); return }
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

  if (authError) {
    return (
      <div className="digest-prefs">
        <div className="dp-inner">
          <h1 className="dp-title">Email digest preferences</h1>
          <div className="dp-notice" role="status">
            <p>
              This page needs the <strong>manage preferences</strong> link from
              one of your digest emails — open that link to sign in (it lasts
              an hour, no password needed).
            </p>
            <p>
              Not subscribed yet? <Link to="/digests/subscribe">Sign up for digests</Link>.
            </p>
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
            <label className="dp-check">
              <input
                type="checkbox"
                checked={prefs.daily_enabled}
                onChange={e => update({ daily_enabled: e.target.checked })}
              />
              <span>Daily, when there's news matching your interests</span>
            </label>
          </fieldset>

          <fieldset className="dp-fieldset">
            <legend className="dp-legend">Topics</legend>
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

          <fieldset className="dp-fieldset">
            <legend className="dp-legend">Councilmembers you follow</legend>
            <div className="dp-checkbox-grid">
              {options.reps.map(rep => (
                <label className="dp-check" key={rep.id}>
                  <input
                    type="checkbox"
                    checked={prefs.followed_rep_ids.includes(rep.id)}
                    onChange={() => toggleInList('followed_rep_ids', rep.id)}
                  />
                  <span>{rep.name} <span className="dp-muted">({rep.seat})</span></span>
                </label>
              ))}
            </div>
          </fieldset>

          {prefs.followed_bills.length > 0 && (
            <fieldset className="dp-fieldset">
              <legend className="dp-legend">Bills you follow</legend>
              <ul className="dp-bill-list">
                {prefs.followed_bills.map(bill => (
                  <li key={bill.id}>
                    <span className="dp-bill-id">{bill.identifier}</span> {bill.title}
                    <button
                      type="button"
                      className="dp-bill-remove"
                      onClick={() =>
                        update({ followed_bills: prefs.followed_bills.filter(b => b.id !== bill.id) })
                      }
                    >
                      Unfollow<span className="visually-hidden"> {bill.identifier}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </fieldset>
          )}

          <div className="dp-field">
            <label className="dp-legend" htmlFor={`${uid}-district`}>Your council district</label>
            <select
              className="dp-input"
              id={`${uid}-district`}
              value={prefs.district_id ?? ''}
              onChange={e => update({ district_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">No district preference</option>
              {options.districts.map(d => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.description ? ` — ${d.description}` : ''}
                </option>
              ))}
            </select>
          </div>

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

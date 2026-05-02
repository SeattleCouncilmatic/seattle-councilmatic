import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import CouncilMap from './CouncilMap'
import { DISTRICT_COLORS } from './districtColors'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './RepsIndex.css'

export default function RepsIndex() {
  useDocumentTitle('City Council')
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState(null)
  // Bidirectional active-district sync between CouncilMap and the
  // district cards. Hovering a polygon, hovering a card, or
  // keyboard-focusing a card all set the same state; the map
  // applies the polygon hover-styling + tooltip and the card
  // shows its district-color border + ring. Keyboard users get
  // the same affordance as mouse users.
  const [activeDistrict, setActiveDistrict] = useState(null)

  useEffect(() => {
    fetch('/api/reps/')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(setData)
      .catch(e => setLoadError(e.message))
  }, [])

  return (
    <div className="reps-page">
      <div className="reps-container">
        <nav className="reps-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="reps-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="reps-breadcrumb-current">City Council</span>
        </nav>

        <header className="reps-header">
          <h1 className="reps-h1">Seattle City Council</h1>
          <p className="reps-subtitle">
            Find your district representative by address, or browse the full council below.
          </p>
        </header>

        <section aria-label="Address lookup" className="reps-section reps-section--lead">
          <AddressLookup />
        </section>

        {loadError && (
          <div className="reps-alert" role="alert">
            <AlertCircle size={20} aria-hidden="true" />
            <span>Could not load council data: {loadError}</span>
          </div>
        )}

        {data && (
          <>
            <section aria-label="Council map" className="reps-section">
              <CouncilMap
                districts={data.districts}
                activeDistrict={activeDistrict}
                onDistrictActivate={setActiveDistrict}
              />
            </section>

            <section aria-label="District representatives" className="reps-section">
              <h2 className="reps-section-h2">District Representatives</h2>
              <ul className="reps-card-grid">
                {data.districts.map(d => (
                  <li key={d.number}>
                    <RepMiniCard
                      rep={d.rep}
                      districtName={d.name}
                      description={d.description}
                      districtNumber={d.number}
                      highlighted={activeDistrict === d.number}
                      onActivate={setActiveDistrict}
                    />
                  </li>
                ))}
              </ul>
            </section>

            <section aria-label="At-large representatives" className="reps-section">
              <h2 className="reps-section-h2">At-Large Council Members</h2>
              <p className="reps-section-sub">
                These council members represent the entire city, not a specific district.
              </p>
              <ul className="reps-card-grid">
                {data.at_large.map(rep => (
                  <li key={rep.slug}>
                    <RepMiniCard rep={rep} districtName={rep.district} />
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </div>
  )
}

function RepMiniCard({ rep, districtName, description, districtNumber, highlighted, onActivate }) {
  const accent = districtNumber ? DISTRICT_COLORS[districtNumber] : null
  // Inline style applied when the card is "active" — hovered or
  // focused. Replaces the default gray border with the district
  // accent color and adds a soft matching ring, AND suppresses the
  // browser's :focus-visible outline (.rep-mini-card has one set
  // for at-large cards) so we don't draw a navy ring on top of
  // the district-color ring on focus.
  const highlightStyle = highlighted && accent
    ? { borderColor: accent, boxShadow: `0 0 0 2px ${accent}33`, outline: 'none' }
    : undefined
  const accentBar = accent ? { borderLeftColor: accent } : undefined

  // District cards mirror map polygon click — navigate to the district
  // page (rep + at-large). At-large cards have no districtNumber, so they
  // navigate straight to the rep's detail page.
  const target = districtNumber ? `/reps/district/${districtNumber}` : `/reps/${rep?.slug}`

  // Sync card hover/focus to the shared activeDistrict state. Only
  // fires for districted cards — at-large cards have no map polygon
  // to highlight, and we don't want a stray onActivate(null) from an
  // at-large blur to clear an active state set by a districted card.
  const activateHandlers = districtNumber ? {
    onMouseEnter: () => onActivate?.(districtNumber),
    onMouseLeave: () => onActivate?.(null),
    onFocus: () => onActivate?.(districtNumber),
    onBlur: () => onActivate?.(null),
  } : {}

  if (!rep) {
    // Vacant seat still wants to surface the district context, so keep
    // the link active even without a rep — the district page handles
    // the "currently vacant" copy.
    return (
      <Link
        to={target}
        className={`rep-mini-card rep-mini-card--empty${accent ? ' rep-mini-card--accented' : ''}`}
        style={{ ...accentBar, ...highlightStyle }}
        {...activateHandlers}
      >
        <div className="rep-mini-card-district">{districtName}</div>
        <div className="rep-mini-card-name">Vacant</div>
      </Link>
    )
  }
  return (
    <Link
      to={target}
      className={`rep-mini-card${accent ? ' rep-mini-card--accented' : ''}`}
      style={{ ...accentBar, ...highlightStyle }}
      {...activateHandlers}
    >
      <div className="rep-mini-card-district">{districtName}</div>
      <div className="rep-mini-card-name">{rep.name}</div>
      {description && <div className="rep-mini-card-desc">{description}</div>}
    </Link>
  )
}

function AddressLookup() {
  const navigate = useNavigate()
  const [address, setAddress] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!address.trim()) {
      setError('Please enter an address')
      return
    }
    setLoading(true); setError(null)
    try {
      const r = await fetch('/api/reps/lookup/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: address.trim() }),
      })
      const data = await r.json()
      if (data.success && data.data?.district?.number) {
        navigate(`/reps/district/${data.data.district.number}`)
      } else {
        setError(data.error || 'Address not found')
      }
    } catch (err) {
      setError('Failed to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="reps-lookup">
      <form onSubmit={submit} className="reps-lookup-form">
        <label className="reps-lookup-field">
          <span className="reps-lookup-label">Find your representative by address</span>
          <input
            type="text"
            className="reps-lookup-input"
            placeholder="123 Main St, Seattle"
            value={address}
            onChange={e => setAddress(e.target.value)}
            autoFocus
          />
        </label>
        <button type="submit" className="reps-lookup-btn" disabled={loading}>
          {loading ? 'Looking up…' : 'Look up'}
        </button>
      </form>

      {error && (
        <div className="reps-alert" role="alert">
          <AlertCircle size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}

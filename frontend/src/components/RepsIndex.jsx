import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MapPin, AlertCircle } from 'lucide-react'
import CouncilMap from './CouncilMap'
import './RepsIndex.css'

export default function RepsIndex() {
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    fetch('/api/reps/')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(setData)
      .catch(e => setLoadError(e.message))
  }, [])

  return (
    <main className="reps-page">
      <div className="reps-container">
        <nav className="reps-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">This Week</Link>
          <span className="reps-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="reps-breadcrumb-current">My Council Members</span>
        </nav>

        <header className="reps-header">
          <h1 className="reps-h1">Seattle City Council</h1>
          <p className="reps-subtitle">
            Click a district on the map to see its representative, or look up your reps by address.
          </p>
        </header>

        {loadError && (
          <div className="reps-alert" role="alert">
            <AlertCircle size={20} aria-hidden="true" />
            <span>Could not load council data: {loadError}</span>
          </div>
        )}

        {data && (
          <>
            <section aria-label="Council map">
              <CouncilMap districts={data.districts} />
            </section>

            <section aria-label="District representatives" className="reps-section">
              <h2 className="reps-section-h2">District Representatives</h2>
              <ul className="reps-card-grid">
                {data.districts.map(d => (
                  <li key={d.number}>
                    <RepMiniCard rep={d.rep} districtName={d.name} description={d.description} />
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

            <section aria-label="Address lookup" className="reps-section">
              <h2 className="reps-section-h2">Find Your Representatives by Address</h2>
              <AddressLookup />
            </section>
          </>
        )}
      </div>
    </main>
  )
}

function RepMiniCard({ rep, districtName, description }) {
  if (!rep) {
    return (
      <div className="rep-mini-card rep-mini-card--empty">
        <div className="rep-mini-card-district">{districtName}</div>
        <div className="rep-mini-card-name">Vacant</div>
      </div>
    )
  }
  return (
    <Link to={`/reps/${rep.slug}`} className="rep-mini-card">
      <div className="rep-mini-card-district">{districtName}</div>
      <div className="rep-mini-card-name">{rep.name}</div>
      {description && <div className="rep-mini-card-desc">{description}</div>}
    </Link>
  )
}

function AddressLookup() {
  const [address, setAddress] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!address.trim()) {
      setError('Please enter an address')
      return
    }
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await fetch('/api/reps/lookup/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: address.trim() }),
      })
      const data = await r.json()
      if (data.success) setResult(data.data)
      else setError(data.error || 'Address not found')
    } catch (err) {
      setError('Failed to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="reps-lookup">
      <form onSubmit={submit} className="reps-lookup-form">
        <input
          type="text"
          className="reps-lookup-input"
          placeholder="123 Main St, Seattle"
          value={address}
          onChange={e => setAddress(e.target.value)}
          aria-label="Address"
        />
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

      {result && (
        <div className="reps-lookup-result" role="status">
          <MapPin size={18} aria-hidden="true" />
          <span>
            Your address is in <strong>{result.district.name}</strong>.
          </span>
          <ul className="reps-lookup-rep-list">
            {result.representatives.map(r => (
              <li key={r.district + r.name}>
                <strong>{r.name}</strong> · {r.district}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import NotFound from './NotFound'
import DistrictMiniMap from './DistrictMiniMap'
import { DISTRICT_COLORS } from './districtColors'
import './RepDistrict.css'

export default function RepDistrict() {
  const { number } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
    fetch(`/api/reps/districts/${encodeURIComponent(number)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [number])

  if (status === 404) return <NotFound />
  if (error) return (
    <div className="rep-district-page"><div className="rep-district-container">Could not load: {error}</div></div>
  )
  if (!data) return (
    <div className="rep-district-page"><div className="rep-district-container">Loading…</div></div>
  )

  const accent = DISTRICT_COLORS[data.district.number] || '#2E3D5B'

  return (
    <div className="rep-district-page">
      <div className="rep-district-container">
        <nav className="rep-district-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="rep-district-breadcrumb-sep" aria-hidden="true">/</span>
          <Link to="/reps">City Council</Link>
          <span className="rep-district-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="rep-district-breadcrumb-current">{data.district.name}</span>
        </nav>

        <header className="rep-district-header" style={{ borderLeftColor: accent }}>
          <div className="rep-district-eyebrow" style={{ color: accent }}>District</div>
          <h1 className="rep-district-h1">{data.district.name}</h1>
          {data.district.description && (
            <p className="rep-district-sub">{data.district.description}</p>
          )}
        </header>

        {data.district.geometry && (
          <section className="rep-district-section" aria-label="District map">
            <DistrictMiniMap
              geometry={data.district.geometry}
              districtNumber={data.district.number}
            />
          </section>
        )}

        <section className="rep-district-section" aria-label="Your district representative">
          <h2 className="rep-district-h2">Your District Representative</h2>
          {data.rep ? (
            <RepCardLink rep={data.rep} accent={accent} />
          ) : (
            <p className="rep-district-empty">This district seat is currently vacant.</p>
          )}
        </section>

        <section className="rep-district-section" aria-label="At-large representatives">
          <h2 className="rep-district-h2">At-Large Council Members</h2>
          <p className="rep-district-section-sub">
            These council members represent every resident of Seattle, including you.
          </p>
          <ul className="rep-district-card-grid">
            {data.at_large.map(rep => (
              <li key={rep.slug}>
                <RepCardLink rep={rep} />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}

function RepCardLink({ rep, accent }) {
  return (
    <Link
      to={`/reps/${rep.slug}`}
      className="rep-district-card"
      style={accent ? { borderLeftColor: accent } : undefined}
    >
      <div className="rep-district-card-position">{rep.district}</div>
      <div className="rep-district-card-name">{rep.name}</div>
      {rep.email && <div className="rep-district-card-meta">{rep.email}</div>}
    </Link>
  )
}

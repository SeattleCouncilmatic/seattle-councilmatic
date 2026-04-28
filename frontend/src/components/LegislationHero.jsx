import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import './LegislationHero.css'

// Homepage hero. The Seattle skyline background sets the place; the
// search input over it points users straight at the legislation index.
// Submitting navigates to /legislation?q=<query>, which LegislationIndex
// already understands — no extra plumbing on the index side.
export default function LegislationHero() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const term = q.trim()
    if (term) {
      navigate(`/legislation?q=${encodeURIComponent(term)}`)
    } else {
      // Empty submit drops the user on the index without a filter.
      navigate('/legislation')
    }
  }

  return (
    <div className="home-hero">
      <div className="home-hero-overlay" />
      <div className="home-hero-content">
        <h2 className="home-hero-title">Search Seattle Legislation</h2>
        <p className="home-hero-subtitle">
          Find bills, resolutions, and council actions by identifier or keyword.
        </p>

        <form onSubmit={submit} className="home-hero-form" role="search">
          <label className="sr-only" htmlFor="home-hero-search">
            Search Seattle legislation
          </label>
          <div className="home-hero-input-wrapper">
            <Search className="home-hero-search-icon" size={22} aria-hidden="true" />
            <input
              id="home-hero-search"
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by identifier or title (e.g. parking, CB 119901)…"
              className="home-hero-search-input"
              autoComplete="off"
            />
            <button type="submit" className="home-hero-search-btn">
              Search
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

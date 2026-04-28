import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import './LegislationHero.css'

// Homepage hero. The Seattle skyline sets the place; the search box
// over it points users at the unified /search results page (which
// fans out to legislation + municipal code in parallel). Submitting
// navigates there with q=<query>; empty submit drops users on the
// browse-mode legislation index.
export default function LegislationHero() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const term = q.trim()
    if (term) {
      navigate(`/search?q=${encodeURIComponent(term)}`)
    } else {
      navigate('/legislation')
    }
  }

  return (
    <div className="home-hero">
      <div className="home-hero-overlay" />
      <div className="home-hero-content">
        <h2 className="home-hero-title">Search Seattle Government</h2>
        <p className="home-hero-subtitle">
          Find bills, resolutions, and the Municipal Code in one search.
        </p>

        <form onSubmit={submit} className="home-hero-form" role="search">
          <label className="sr-only" htmlFor="home-hero-search">
            Search Seattle legislation and Municipal Code
          </label>
          <div className="home-hero-input-wrapper">
            <Search className="home-hero-search-icon" size={22} aria-hidden="true" />
            <input
              id="home-hero-search"
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search a topic (e.g. parking) or citation (e.g. CB 119901, 23.47A)…"
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

import { Search, Loader2 } from 'lucide-react';
import './HeroSection.css';

export default function HeroSection({ address, onChange, onSubmit, loading }) {
  return (
    <div className="hero-section">
      <div className="hero-overlay" />
      <div className="hero-content">
        <h2 className="hero-title">Find Your Council Members</h2>
        <p className="hero-subtitle">
          Enter your address to identify your City Council district and representatives.
          Learn about who represents you and how to contact them.
        </p>

        <form onSubmit={onSubmit} className="hero-search-form" role="search">
          <label className="sr-only" htmlFor="hero-address-input">
            Enter your address to find your council members
          </label>
          <div className="hero-input-wrapper">
            <Search className="hero-search-icon" size={22} aria-hidden="true" />
            <input
              id="hero-address-input"
              type="text"
              value={address}
              onChange={onChange}
              placeholder="Enter your address to find your council members..."
              className="hero-search-input"
              disabled={loading}
              autoComplete="street-address"
            />
            <button
              type="submit"
              className="hero-search-btn"
              disabled={loading || !address.trim()}
            >
              {loading ? (
                <Loader2 className="spinning" size={18} aria-hidden="true" />
              ) : (
                'Search'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

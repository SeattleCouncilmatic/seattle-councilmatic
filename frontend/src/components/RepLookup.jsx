import { useState } from 'react';
import { Search, MapPin, Users, AlertCircle, Loader2 } from 'lucide-react';
import DistrictMap from './DistrictMap';
import './RepLookup.css';

export default function RepLookup() {
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!address.trim()) {
      setError('Please enter an address');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch('http://localhost:8000/api/reps/lookup/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ address: address.trim() }),
      });

      const data = await response.json();

      if (data.success) {
        setResult(data.data);
      } else {
        setError(data.error || 'Address not found');
      }
    } catch (err) {
      setError('Failed to connect to the server. Please try again.');
      console.error('Lookup error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setAddress('');
    setResult(null);
    setError(null);
  };

  return (
    <div className="rep-lookup">
      <div className="rep-lookup-container">
        <div className="rep-lookup-header">
          <Users className="header-icon" size={32} />
          <h1>Find Your City Council Representative</h1>
          <p>Enter your Seattle address to find your city council district and representatives</p>
        </div>

        <form onSubmit={handleSubmit} className="lookup-form">
          <div className="input-group">
            <MapPin className="input-icon" size={20} />
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Enter your Seattle address (e.g., 123 Main St, Seattle, WA)"
              className="address-input"
              disabled={loading}
            />
          </div>

          <div className="button-group">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !address.trim()}
            >
              {loading ? (
                <>
                  <Loader2 className="btn-icon spinning" size={20} />
                  Looking up...
                </>
              ) : (
                <>
                  <Search className="btn-icon" size={20} />
                  Find My District
                </>
              )}
            </button>

            {(result || error) && (
              <button
                type="button"
                onClick={handleClear}
                className="btn btn-secondary"
              >
                Clear
              </button>
            )}
          </div>
        </form>

        {error && (
          <div className="alert alert-error">
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        )}

        {result && (
          <div className="result-card">
            <div className="result-header">
              <MapPin size={24} />
              <h2>Your District</h2>
            </div>

            <div className="district-info">
              <div className="district-number">
                District {result.district.number}
              </div>
            </div>

            {result.district.geometry && (
              <DistrictMap geometry={result.district.geometry} />
            )}

            {result.representatives && result.representatives.length > 0 ? (
              <div className="representatives">
                <h3>Your Representatives</h3>
                {result.representatives.map((rep, index) => (
                  <div key={index} className="rep-card">
                    <div className="rep-header">
                      <Users size={20} />
                      <div>
                        <h4>{rep.name}</h4>
                        <span className="rep-district-label">{rep.district}</span>
                      </div>
                    </div>
                    <p className="rep-role">{rep.role}</p>
                    <div className="rep-contact">
                      {rep.email && (
                        <a href={`mailto:${rep.email}`} className="contact-link">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                            <polyline points="22,6 12,13 2,6" />
                          </svg>
                          {rep.email}
                        </a>
                      )}
                      {rep.profile_url && (
                        <a href={rep.profile_url} target="_blank" rel="noopener noreferrer" className="contact-link">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                            <polyline points="15 3 21 3 21 9" />
                            <line x1="10" y1="14" x2="21" y2="3" />
                          </svg>
                          View Profile
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="no-reps">
                <p>No representative data available for this district.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from 'react';
import { Search, MapPin, Users, AlertCircle, Loader2 } from 'lucide-react';
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
              <p className="district-name">{result.district.name}</p>
            </div>

            {result.representatives && result.representatives.length > 0 ? (
              <div className="representatives">
                <h3>Your Representatives</h3>
                <ul>
                  {result.representatives.map((rep, index) => (
                    <li key={index} className="rep-item">
                      <strong>{rep.name}</strong>
                      {rep.title && <span className="rep-title">{rep.title}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="no-reps">
                <p>Representative information coming soon!</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from 'react';
import { MapPin, Phone, Mail, ExternalLink, Users, AlertCircle, Clock } from 'lucide-react';
import DistrictMap from './DistrictMap';
import HeroSection from './HeroSection';
import './RepLookup.css';

function RepCard({ rep }) {
  const isAtLarge = rep.district && rep.district.toLowerCase().includes('position');
  const districtLabel = isAtLarge
    ? rep.district.replace('Position', 'Position').toUpperCase()
    : rep.district.toUpperCase();

  return (
    <div className="rep-card-v2">
      <div className="rep-card-photo-wrapper">
        {rep.photo_url ? (
          <img
            src={rep.photo_url}
            alt={rep.name}
            className="rep-card-photo"
          />
        ) : (
          <div className="rep-card-photo-placeholder" aria-hidden="true">
            <Users size={32} />
          </div>
        )}
      </div>

      <div className="rep-card-district-chip">{districtLabel}</div>

      <h4 className="rep-card-name">{rep.name}</h4>

      {rep.district_description && (
        <p className="rep-card-area">{rep.district_description}</p>
      )}

      <div className="rep-card-contacts">
        {rep.phone && (
          <div className="rep-contact-row">
            <Phone size={15} className="rep-contact-icon" aria-hidden="true" />
            <div>
              <span className="rep-contact-label">Phone</span>
              <a href={`tel:${rep.phone}`} className="rep-contact-value">
                {rep.phone}
              </a>
            </div>
          </div>
        )}
        {rep.email && (
          <div className="rep-contact-row">
            <Mail size={15} className="rep-contact-icon" aria-hidden="true" />
            <div>
              <span className="rep-contact-label">Email</span>
              <a href={`mailto:${rep.email}`} className="rep-contact-value">
                {rep.email}
              </a>
            </div>
          </div>
        )}
      </div>

      <div className="rep-card-actions">
        {rep.profile_url && (
          <a
            href={rep.profile_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rep-action-btn rep-action-btn--outline"
          >
            Voting Record
            <ExternalLink size={13} aria-hidden="true" />
          </a>
        )}
        {rep.office_hours_url ? (
          <a
            href={rep.office_hours_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rep-action-btn rep-action-btn--outline"
          >
            Office Hours
            <Clock size={13} aria-hidden="true" />
          </a>
        ) : (
          <button className="rep-action-btn rep-action-btn--outline" disabled>
            Office Hours
          </button>
        )}
      </div>
    </div>
  );
}

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
      const response = await fetch('/api/reps/lookup/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
    <>
      <HeroSection
        address={address}
        onChange={(e) => setAddress(e.target.value)}
        onSubmit={handleSubmit}
        loading={loading}
      />

      <div className="rep-lookup-body">
        {error && (
          <div className="alert alert-error" role="alert">
            <AlertCircle size={20} aria-hidden="true" />
            <span>{error}</span>
            <button
              className="alert-clear-btn"
              onClick={handleClear}
              aria-label="Dismiss error"
            >
              ×
            </button>
          </div>
        )}

        {result && (
          <div className="result-section">
            <div className="result-district-header">
              <MapPin size={20} aria-hidden="true" />
              <span>
                Your address is in <strong>{result.district.name}</strong>
              </span>
            </div>

            {result.district.geometry && (
              <DistrictMap geometry={result.district.geometry} />
            )}

            {result.representatives && result.representatives.length > 0 ? (
              <section aria-label="Your Representatives">
                <p className="reps-eyebrow">YOUR REPRESENTATIVES</p>
                <h2 className="reps-heading">Based on your location</h2>
                <div className="rep-cards-grid">
                  {result.representatives.map((rep, index) => (
                    <RepCard key={index} rep={rep} />
                  ))}
                </div>
              </section>
            ) : (
              <div className="no-reps">
                <p>No representative data available for this district.</p>
              </div>
            )}

            <button className="btn-clear-results" onClick={handleClear}>
              Search a different address
            </button>
          </div>
        )}
      </div>
    </>
  );
}

import { Link } from 'react-router-dom'
import './LegislationCard.css';

const VARIANT_CLASSES = {
  yellow: 'tag--yellow',
  green:  'tag--green',
  red:    'tag--red',
  blue:   'tag--blue',
  gray:   'tag--gray',
};

function StatusTag({ label, variant }) {
  const cls = VARIANT_CLASSES[variant] || 'tag--gray';
  return <span className={`status-tag ${cls}`}>{label}</span>;
}

function formatDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function LegislationCard({ bill }) {
  const {
    identifier,
    title,
    sponsor,
    status,
    status_variant,
    date_introduced,
    slug,
  } = bill;

  return (
    <article className="leg-card">
      <p className="leg-card-identifier">{identifier}</p>

      <h4 className="leg-card-title">
        {slug ? (
          <Link to={`/legislation/${slug}`} className="leg-card-link">
            {title}
          </Link>
        ) : (
          title
        )}
      </h4>

      {sponsor && (
        <p className="leg-card-sponsor">Sponsor: {sponsor}</p>
      )}

      <div className="leg-card-footer">
        <StatusTag label={status} variant={status_variant} />
        {date_introduced && (
          <span className="leg-card-date">Introduced: {formatDate(date_introduced)}</span>
        )}
      </div>
    </article>
  );
}

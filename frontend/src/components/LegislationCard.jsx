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
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function LegislationCard({ bill, backToSearch }) {
  const {
    identifier,
    title,
    title_highlighted,
    sponsor,
    status,
    status_variant,
    date_introduced,
    slug,
    is_primary,
  } = bill;

  // When the card is rendered inside the legislation index, the parent passes
  // the current URL search params so the detail page can render a breadcrumb
  // link that returns to the same filtered/paginated view. Cards rendered
  // outside the index (e.g. ThisWeek) leave it undefined, which falls back to
  // a fresh /legislation view.
  const linkState = backToSearch ? { backToSearch } : undefined;

  // When the API returns title_highlighted (search results with q), the
  // string is HTML-escaped server-side and only the <mark> tags we
  // injected are live — safe for dangerouslySetInnerHTML.
  const titleNode = title_highlighted
    ? <span dangerouslySetInnerHTML={{ __html: title_highlighted }} />
    : title;

  return (
    <article className="leg-card">
      <div className="leg-card-identifier-row">
        <p className="leg-card-identifier">{identifier}</p>
        {is_primary !== undefined && (
          <span className={`leg-card-role-tag${is_primary ? ' leg-card-role-tag--primary' : ''}`}>
            {is_primary ? 'Primary' : 'Co-sponsor'}
          </span>
        )}
      </div>

      <h4 className="leg-card-title">
        {slug ? (
          <Link to={`/legislation/${slug}`} state={linkState} className="leg-card-link">
            {titleNode}
          </Link>
        ) : (
          titleNode
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

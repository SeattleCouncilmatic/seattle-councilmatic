import { Link } from 'react-router-dom'
import './EventCard.css';

const TYPE_CHIP_CLASSES = {
  Council:   'evt-type-chip--council',
  Briefing:  'evt-type-chip--briefing',
  Committee: 'evt-type-chip--committee',
  Hearing:   'evt-type-chip--hearing',
  Other:     'evt-type-chip--other',
};

function formatEventDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  return d.toLocaleString('en-US', {
    weekday: 'short',
    month:   'short',
    day:     'numeric',
    hour:    'numeric',
    minute:  '2-digit',
  });
}

function TypeChip({ type }) {
  if (!type) return null;
  const cls = TYPE_CHIP_CLASSES[type] || TYPE_CHIP_CLASSES.Other;
  return <span className={`evt-type-chip ${cls}`}>{type}</span>;
}

function DocLinks({ agendaUrl, packetUrl, minutesUrl, legistarUrl }) {
  const links = [
    agendaUrl   && { url: agendaUrl,   label: 'Agenda' },
    packetUrl   && { url: packetUrl,   label: 'Packet' },
    minutesUrl  && { url: minutesUrl,  label: 'Minutes' },
    legistarUrl && { url: legistarUrl, label: 'Legistar ↗' },
  ].filter(Boolean);
  if (links.length === 0) return null;
  return (
    <div className="evt-card-links">
      {links.map((l, i) => (
        <a
          key={i}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer"
          className="evt-card-link-pill"
          onClick={(e) => e.stopPropagation()}
        >
          {l.label}
        </a>
      ))}
    </div>
  );
}

export default function EventCard({ event, backToSearch }) {
  const {
    name,
    type,
    start_date,
    description,
    slug,
    agenda_file_url,
    agenda_status,
    packet_url,
    minutes_file_url,
    legistar_url,
  } = event;

  const cancelled = (agenda_status || '').toLowerCase() === 'cancelled';

  // When the card is rendered inside the events index, the parent passes
  // the current URL search params so the detail page can render a
  // breadcrumb that returns to the same filtered view. Cards rendered
  // outside the index (e.g. ThisWeek) leave it undefined.
  const linkState = backToSearch ? { backToSearch } : undefined;

  return (
    <article className={`evt-card${cancelled ? ' evt-card--cancelled' : ''}`}>
      <div>
        <div className="evt-card-title-row">
          <TypeChip type={type} />
          {cancelled && <span className="evt-card-cancelled-badge">Cancelled</span>}
          <h3 className="evt-card-title">
            {slug ? (
              <Link to={`/events/${slug}`} state={linkState} className="evt-card-link">
                {name}
              </Link>
            ) : (
              name
            )}
          </h3>
        </div>
        <p className="evt-card-date">{formatEventDate(start_date)}</p>
      </div>
      {description && (
        <p className="evt-card-description">{description}</p>
      )}
      <DocLinks
        agendaUrl={agenda_file_url}
        packetUrl={packet_url}
        minutesUrl={minutes_file_url}
        legistarUrl={legistar_url}
      />
    </article>
  );
}

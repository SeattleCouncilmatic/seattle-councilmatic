import { Link } from 'react-router-dom'
import './EventCard.css';

const TYPE_CHIP_CLASSES = {
  Council:   'event-type-chip--council',
  Briefing:  'event-type-chip--briefing',
  Committee: 'event-type-chip--committee',
  Hearing:   'event-type-chip--hearing',
  Other:     'event-type-chip--other',
};

function formatEventDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  // Time portion deliberately omitted: Legistar's EventTime isn't in
  // our scrape, so start_date always carries midnight-Pacific. Showing
  // it would be misleading. Restore hour/minute once the scraper picks
  // up EventTime — see the "Events: capture EventTime in pupa scraper"
  // follow-up in WORK_LOG.
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month:   'short',
    day:     'numeric',
  });
}

function TypeChip({ type }) {
  if (!type) return null;
  const cls = TYPE_CHIP_CLASSES[type] || TYPE_CHIP_CLASSES.Other;
  return <span className={`event-type-chip ${cls}`}>{type}</span>;
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
    <div className="event-card-links">
      {links.map((l, i) => (
        <a
          key={i}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer"
          className="event-card-link-pill"
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
    <article className={`meeting-card${cancelled ? ' meeting-card--cancelled' : ''}`}>
      <div>
        <div className="event-card-title-row">
          <TypeChip type={type} />
          {cancelled && <span className="event-card-cancelled-badge">Cancelled</span>}
          <h4 className="meeting-card-title">
            {slug ? (
              <Link to={`/events/${slug}`} state={linkState} className="meeting-card-link">
                {name}
              </Link>
            ) : (
              name
            )}
          </h4>
        </div>
        <p className="meeting-card-date">{formatEventDate(start_date)}</p>
      </div>
      {description && (
        <p className="meeting-card-description">{description}</p>
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

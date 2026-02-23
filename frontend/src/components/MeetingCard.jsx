import './MeetingCard.css';

function formatMeetingDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month:   'short',
    day:     'numeric',
    hour:    'numeric',
    minute:  '2-digit',
  });
}

export default function MeetingCard({ meeting }) {
  const { name, start_date, description, slug } = meeting;

  return (
    <article className="meeting-card">
      <div>
        <h4 className="meeting-card-title">
          {slug ? (
            <a href={`/events/${slug}/`} className="meeting-card-link">
              {name}
            </a>
          ) : (
            name
          )}
        </h4>
        <p className="meeting-card-date">{formatMeetingDate(start_date)}</p>
      </div>
      {description && (
        <p className="meeting-card-description">{description}</p>
      )}
    </article>
  );
}

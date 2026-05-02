import { useState, useEffect } from 'react';
import { Gavel, CalendarDays, ArrowRight, Loader2 } from 'lucide-react';
import LegislationCard from './LegislationCard';
import EventCard from './EventCard';
import './ThisWeek.css';

function SectionHeader({ icon: Icon, title, subtitle }) {
  return (
    <div className="tw-section-header">
      <h2 className="tw-section-title">
        <Icon className="tw-section-icon" size={36} aria-hidden="true" />
        {title}
      </h2>
      <p className="tw-section-subtitle">{subtitle}</p>
    </div>
  );
}

function ViewAllLink({ href, label }) {
  return (
    <a href={href} className="tw-view-all">
      {label}
      <ArrowRight size={18} aria-hidden="true" />
    </a>
  );
}

function LoadingSpinner() {
  return (
    <div role="status" className="tw-loading" aria-label="Loading">
      <Loader2 className="tw-spinner" size={28} />
    </div>
  );
}

function ErrorMessage({ message }) {
  return <p role="alert" className="tw-error">{message}</p>;
}

export default function ThisWeek() {
  const [bills, setBills] = useState([]);
  const [events, setEvents] = useState([]);
  const [billsLoading, setBillsLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [billsError, setBillsError] = useState(null);
  const [eventsError, setEventsError] = useState(null);

  useEffect(() => {
    fetch('/api/legislation/recent/?limit=4')
      .then((r) => r.json())
      .then((data) => setBills(data.results || []))
      .catch(() => setBillsError('Could not load legislation.'))
      .finally(() => setBillsLoading(false));
  }, []);

  useEffect(() => {
    fetch('/api/events/upcoming/?limit=4')
      .then((r) => r.json())
      .then((data) => setEvents(data.results || []))
      .catch(() => setEventsError('Could not load events.'))
      .finally(() => setEventsLoading(false));
  }, []);

  return (
    <section id="this-week" className="this-week">
      <div className="tw-inner">
        <div className="tw-grid">

          {/* ── New Legislation ── */}
          <div>
            <SectionHeader
              icon={Gavel}
              title="Recent Legislation"
              subtitle="Bills and resolutions introduced recently."
            />
            {billsLoading && <LoadingSpinner />}
            {billsError && <ErrorMessage message={billsError} />}
            {!billsLoading && !billsError && (
              <div className="tw-card-list">
                {bills.length > 0
                  ? bills.map((bill) => (
                      <LegislationCard key={bill.identifier} bill={bill} />
                    ))
                  : <p className="tw-empty">No recent legislation found.</p>
                }
              </div>
            )}
            <ViewAllLink href="/legislation/" label="View All Legislation" />
          </div>

          {/* ── Upcoming Events ── */}
          <div>
            <SectionHeader
              icon={CalendarDays}
              title="Upcoming Events"
              subtitle="Council and committee meetings scheduled soon."
            />
            {eventsLoading && <LoadingSpinner />}
            {eventsError && <ErrorMessage message={eventsError} />}
            {!eventsLoading && !eventsError && (
              <div className="tw-card-list">
                {events.length > 0
                  ? events.map((event, i) => (
                      <EventCard key={i} event={event} />
                    ))
                  : <p className="tw-empty">No upcoming events found.</p>
                }
              </div>
            )}
            <ViewAllLink href="/events/" label="View All Events" />
          </div>

        </div>
      </div>
    </section>
  );
}

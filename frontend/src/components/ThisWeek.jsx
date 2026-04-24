import { useState, useEffect } from 'react';
import { Gavel, CalendarDays, ArrowRight, Loader2 } from 'lucide-react';
import LegislationCard from './LegislationCard';
import MeetingCard from './MeetingCard';
import './ThisWeek.css';

function SectionHeader({ icon: Icon, title, subtitle }) {
  return (
    <div className="tw-section-header">
      <h3 className="tw-section-title">
        <Icon className="tw-section-icon" size={36} aria-hidden="true" />
        {title}
      </h3>
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
    <div className="tw-loading" aria-label="Loading">
      <Loader2 className="tw-spinner" size={28} />
    </div>
  );
}

function ErrorMessage({ message }) {
  return <p className="tw-error">{message}</p>;
}

export default function ThisWeek() {
  const [bills, setBills] = useState([]);
  const [meetings, setMeetings] = useState([]);
  const [billsLoading, setBillsLoading] = useState(true);
  const [meetingsLoading, setMeetingsLoading] = useState(true);
  const [billsError, setBillsError] = useState(null);
  const [meetingsError, setMeetingsError] = useState(null);

  useEffect(() => {
    fetch('/api/legislation/recent/?limit=4')
      .then((r) => r.json())
      .then((data) => setBills(data.results || []))
      .catch(() => setBillsError('Could not load legislation.'))
      .finally(() => setBillsLoading(false));
  }, []);

  useEffect(() => {
    fetch('/api/meetings/upcoming/?limit=4')
      .then((r) => r.json())
      .then((data) => setMeetings(data.results || []))
      .catch(() => setMeetingsError('Could not load meetings.'))
      .finally(() => setMeetingsLoading(false));
  }, []);

  return (
    <section id="this-week" className="this-week" aria-labelledby="tw-heading">
      <div className="tw-inner">
        <div className="tw-grid">

          {/* ── New Legislation ── */}
          <div>
            <SectionHeader
              icon={Gavel}
              title="New Legislation"
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

          {/* ── Upcoming Meetings ── */}
          <div>
            <SectionHeader
              icon={CalendarDays}
              title="Upcoming Meetings"
              subtitle="Public meetings scheduled soon."
            />
            {meetingsLoading && <LoadingSpinner />}
            {meetingsError && <ErrorMessage message={meetingsError} />}
            {!meetingsLoading && !meetingsError && (
              <div className="tw-card-list">
                {meetings.length > 0
                  ? meetings.map((meeting, i) => (
                      <MeetingCard key={i} meeting={meeting} />
                    ))
                  : <p className="tw-empty">No upcoming meetings found.</p>
                }
              </div>
            )}
            <ViewAllLink href="/events/" label="View All Meetings" />
          </div>

        </div>
      </div>
    </section>
  );
}

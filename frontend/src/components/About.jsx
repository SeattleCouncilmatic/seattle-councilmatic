import { Link } from 'react-router-dom'
import './About.css'

const REPO_URL = 'https://github.com/SeattleCouncilmatic/seattle-councilmatic'
const CONTACT_EMAIL = 'jimmie@jimmiewifi.com'

export default function About() {
  return (
    <main className="about-page">
      <div className="about-container">
        <nav className="about-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">This Week</Link>
          <span className="about-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="about-breadcrumb-current">About</span>
        </nav>

        <header className="about-header">
          <h1 className="about-h1">About Seattle Councilmatic</h1>
          <p className="about-lead">
            A window into Seattle City Council — bills, meetings, council
            members, and the Municipal Code, in a form that's actually
            browsable and searchable.
          </p>
        </header>

        <section className="about-section" aria-label="Why this exists">
          <h2 className="about-h2">Why this exists</h2>
          <p>
            The City of Seattle's records are public, but the official portal is
            hard to navigate and the Municipal Code is a 4,300-page PDF. This
            site puts the same data behind a single search box and a familiar
            set of pages, so residents can follow what the Council is doing
            without learning the city's tooling.
          </p>
        </section>

        <section className="about-section" aria-label="What's on the site">
          <h2 className="about-h2">What's on the site</h2>
          <ul className="about-feature-list">
            <li>
              <Link to="/">This Week</Link> — recent legislation and upcoming
              meetings at a glance.
            </li>
            <li>
              <Link to="/legislation">Legislation</Link> — every bill and
              resolution, searchable by identifier or title.
            </li>
            <li>
              <Link to="/events">Events</Link> — committee meetings and council
              briefings with their agendas and packets.
            </li>
            <li>
              <Link to="/reps">My Council Members</Link> — district map, address
              lookup, and rep profiles.
            </li>
            <li>
              <Link to="/municode">Municipal Code</Link> — search and browse
              all 7,400+ sections of the SMC.
            </li>
            <li>
              <Link to="/search">Search</Link> — one search box across
              legislation and the Municipal Code.
            </li>
          </ul>
        </section>

        <section className="about-section" aria-label="Where the data comes from">
          <h2 className="about-h2">Where the data comes from</h2>
          <ul className="about-bullets">
            <li>
              Bills, sponsors, actions, votes, and events: scraped nightly from{' '}
              <a href="https://seattle.legistar.com" target="_blank" rel="noopener noreferrer">
                seattle.legistar.com
              </a>.
            </li>
            <li>
              Council members and district boundaries: published by the{' '}
              <a href="https://www.seattle.gov/council" target="_blank" rel="noopener noreferrer">
                Seattle City Council
              </a> and the{' '}
              <a href="https://data.seattle.gov" target="_blank" rel="noopener noreferrer">
                City of Seattle Open Data Portal
              </a>.
            </li>
            <li>
              Municipal Code: parsed from the official PDF published by the
              Seattle City Clerk.
            </li>
          </ul>
        </section>

        <section className="about-section" aria-label="Credits">
          <h2 className="about-h2">Built on the work of others</h2>
          <p>
            This site is built on{' '}
            <a href="https://github.com/datamade/django-councilmatic"
               target="_blank" rel="noopener noreferrer">
              django-councilmatic
            </a>, the open-source civic-tech framework maintained by{' '}
            <a href="https://datamade.us" target="_blank" rel="noopener noreferrer">
              DataMade
            </a>. With particular thanks to:
          </p>
          <ul className="about-bullets">
            <li>
              <strong>DataMade</strong> for the Councilmatic ecosystem this
              site extends.
            </li>
            <li>
              <strong>The City of Seattle</strong> for publishing public
              records and geographic data in machine-readable form.
            </li>
            <li>
              <strong>CARTO</strong> for the basemap tiles powering the
              council district map.
            </li>
          </ul>
        </section>

        <section className="about-section" aria-label="Source code and contact">
          <h2 className="about-h2">Source code &amp; contact</h2>
          <p>
            Source code lives at{' '}
            <a href={REPO_URL} target="_blank" rel="noopener noreferrer">
              github.com/SeattleCouncilmatic/seattle-councilmatic
            </a> and is MIT-licensed (copyright DataMade and contributors).
            Issues, suggestions, and pull requests are welcome on GitHub.
          </p>
          <p>
            For other questions or feedback, email{' '}
            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
          </p>
        </section>
      </div>
    </main>
  )
}

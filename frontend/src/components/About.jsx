import { Link } from 'react-router-dom'
import useDocumentTitle from '../hooks/useDocumentTitle'
import './About.css'

const REPO_URL = 'https://github.com/SeattleCouncilmatic/seattle-councilmatic'
const CONTACT_EMAIL = 'contact@seattlecouncilmatic.org'

export default function About() {
  useDocumentTitle('About')
  return (
    <div className="about-page">
      <div className="about-container">
        <nav className="about-breadcrumb" aria-label="Breadcrumb">
          <Link to="/">Home</Link>
          <span className="about-breadcrumb-sep" aria-hidden="true">/</span>
          <span className="about-breadcrumb-current">About</span>
        </nav>

        <header className="about-header">
          <h1 className="about-h1">About Seattle Councilmatic</h1>
          <p className="about-lead">
            A free and accessible way to follow what Seattle City Council is
            doing — the bills they're considering, the meetings they're
            holding, who represents you, and the laws on the books.
          </p>
        </header>

        <section className="about-section" aria-label="Why this exists">
          <h2 className="about-h2">Why this exists</h2>
          <p>
            Council business shapes everything from rent rules and building
            codes to business regulations and labor laws. Seattle
            Councilmatic offers tools that allow the people of Seattle to
            follow legislation, find their representatives, and read the
            Municipal Code that governs life in the Emerald City.
          </p>
        </section>

        <section className="about-section" aria-label="What's on the site">
          <h2 className="about-h2">What's on the site</h2>
          <ul className="about-feature-list">
            <li>
              <Link to="/">Home</Link> — recent legislation and upcoming
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
              <Link to="/reps">City Council</Link> — district map, address
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

        <section className="about-section" aria-label="How Seattle City Council works">
          <h2 className="about-h2">How Seattle City Council works</h2>
          <p>
            The Seattle City Council is the legislative body of the City of
            Seattle. It has nine members: seven elected from geographic
            districts (Districts 1–7) and two elected at-large (Position 8
            and Position 9, who represent every district). Council members
            elect one of their own to serve as Council President.
          </p>
          <p>
            The full Council typically meets every Tuesday afternoon to vote
            on legislation that has cleared its committees. Most of the
            actual work — review, amendment, public comment — happens in
            standing committees, which meet on their own schedules and
            cover specific subject areas (transportation, land use, public
            safety, and so on). Committee assignments and agendas live on
            the <Link to="/events">Events</Link> page.
          </p>
          <p>
            The Mayor of Seattle is a separate executive office. The Mayor
            signs or vetoes legislation passed by Council and is responsible
            for executing it through City departments — but does not vote
            on legislation directly.
          </p>
        </section>

        <section className="about-section" aria-label="Types of legislation">
          <h2 className="about-h2">Types of legislation</h2>
          <p>
            Most items the Council acts on fall into one of three categories:
          </p>
          <ul className="about-bullets">
            <li>
              <strong>Council Bill (CB)</strong> — a proposed law working its
              way through committee and full Council. When a Council Bill
              passes and is signed by the Mayor, it becomes an Ordinance.
            </li>
            <li>
              <strong>Ordinance (Ord)</strong> — a passed law. Most
              ordinances become part of the{' '}
              <Link to="/municode">Seattle Municipal Code</Link>; others
              authorize one-time actions like budget appropriations or
              property transactions.
            </li>
            <li>
              <strong>Resolution (Res)</strong> — typically non-binding.
              Used to adopt policies, take positions, recognize individuals
              or organizations, or direct the Council's own internal work.
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
            Councilmatic was originally created by{' '}
            <a href="https://mjumbewu.com" target="_blank" rel="noopener noreferrer">
              Mjumbe Poe
            </a>{' '}
            for Philadelphia in 2011 as a{' '}
            <a href="https://www.codeforamerica.org" target="_blank" rel="noopener noreferrer">
              Code for America
            </a>{' '}
            Fellow — the first fully-developed open data site for municipal
            legislation in the United States. The framework has since grown
            into the{' '}
            <a href="https://www.councilmatic.org" target="_blank" rel="noopener noreferrer">
              Councilmatic family
            </a>{' '}
            of civic-tech sites, maintained by{' '}
            <a href="https://datamade.us" target="_blank" rel="noopener noreferrer">
              DataMade
            </a>. Seattle Councilmatic is built on their open-source{' '}
            <a href="https://github.com/datamade/django-councilmatic"
               target="_blank" rel="noopener noreferrer">
              django-councilmatic
            </a>.
          </p>
          <p>With particular thanks to:</p>
          <ul className="about-bullets">
            <li>
              <strong>Mjumbe Poe</strong> and <strong>Code for America</strong>{' '}
              for inventing this category of civic site.
            </li>
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
    </div>
  )
}

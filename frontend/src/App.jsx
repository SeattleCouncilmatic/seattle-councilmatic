import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import Footer from './components/Footer'
import LegislationHero from './components/LegislationHero'
import ThisWeek from './components/ThisWeek'
import LegislationIndex from './components/LegislationIndex'
import LegislationDetail from './components/LegislationDetail'
import EventsIndex from './components/EventsIndex'
import EventDetail from './components/EventDetail'
import MuniCodeIndex from './components/MuniCodeIndex'
import MuniCodeTitle from './components/MuniCodeTitle'
import MuniCodeChapter from './components/MuniCodeChapter'
import MuniCodeSection from './components/MuniCodeSection'
import MuniCodeAppendix from './components/MuniCodeAppendix'
import RepsIndex from './components/RepsIndex'
import RepDetail from './components/RepDetail'
import RepDistrict from './components/RepDistrict'
import Search from './components/Search'
import About from './components/About'
import NotFound from './components/NotFound'
import useDocumentTitle from './hooks/useDocumentTitle'
import './App.css'

function HomePage() {
  useDocumentTitle(null) // Just "Seattle Councilmatic" — site is the page subject.
  return (
    <>
      <LegislationHero />
      <ThisWeek />
    </>
  )
}

function App() {
  return (
    <BrowserRouter>
      {/* Skip-link for keyboard / screen-reader users — first
          focusable element on every page, visible only when focused.
          Lets users bypass the header + main nav to reach page content
          without tabbing through every nav item. WCAG 2.4.1. */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <Header />
      <main id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/legislation" element={<LegislationIndex />} />
          <Route path="/legislation/" element={<LegislationIndex />} />
          <Route path="/legislation/:slug" element={<LegislationDetail />} />
          <Route path="/events" element={<EventsIndex />} />
          <Route path="/events/" element={<EventsIndex />} />
          <Route path="/events/:slug" element={<EventDetail />} />
          <Route path="/municode" element={<MuniCodeIndex />} />
          <Route path="/municode/" element={<MuniCodeIndex />} />
          <Route path="/municode/:title/appendix/:label" element={<MuniCodeAppendix />} />
          <Route path="/municode/:title/:chapter/:section" element={<MuniCodeSection />} />
          <Route path="/municode/:title/:chapter" element={<MuniCodeChapter />} />
          <Route path="/municode/:slug" element={<MuniCodeTitle />} />
          <Route path="/reps" element={<RepsIndex />} />
          <Route path="/reps/" element={<RepsIndex />} />
          <Route path="/reps/district/:number" element={<RepDistrict />} />
          <Route path="/reps/:slug" element={<RepDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/search/" element={<Search />} />
          <Route path="/about" element={<About />} />
          <Route path="/about/" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </BrowserRouter>
  )
}

export default App

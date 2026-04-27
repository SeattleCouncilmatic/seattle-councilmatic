import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import NavBar from './components/NavBar'
import RepLookup from './components/RepLookup'
import ThisWeek from './components/ThisWeek'
import LegislationIndex from './components/LegislationIndex'
import LegislationDetail from './components/LegislationDetail'
import EventsIndex from './components/EventsIndex'
import EventDetail from './components/EventDetail'
import NotFound from './components/NotFound'
import './App.css'

function HomePage() {
  return (
    <>
      <RepLookup />
      <NavBar activeItem="This Week" />
      <ThisWeek />
    </>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Header />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/legislation" element={<LegislationIndex />} />
        <Route path="/legislation/" element={<LegislationIndex />} />
        <Route path="/legislation/:slug" element={<LegislationDetail />} />
        <Route path="/events" element={<EventsIndex />} />
        <Route path="/events/" element={<EventsIndex />} />
        <Route path="/events/:slug" element={<EventDetail />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

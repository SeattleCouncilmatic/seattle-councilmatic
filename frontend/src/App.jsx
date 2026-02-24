import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import NavBar from './components/NavBar'
import RepLookup from './components/RepLookup'
import ThisWeek from './components/ThisWeek'
import LegislationDetail from './components/LegislationDetail'
import MeetingDetail from './components/MeetingDetail'
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
        <Route path="/legislation/:slug" element={<LegislationDetail />} />
        <Route path="/events/:slug" element={<MeetingDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

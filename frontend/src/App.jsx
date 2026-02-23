import Header from './components/Header'
import NavBar from './components/NavBar'
import RepLookup from './components/RepLookup'
import ThisWeek from './components/ThisWeek'
import './App.css'

function App() {
  return (
    <>
      <Header />
      <RepLookup />
      <NavBar activeItem="This Week" />
      <ThisWeek />
    </>
  )
}

export default App

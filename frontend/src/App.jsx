import Header from './components/Header'
import RepLookup from './components/RepLookup'
import './App.css'

function App() {
  return (
    <>
      <Header />

      {/* Banner Section */}
      <div className="home-banner" style={{ width: '100%', height: '350px', backgroundColor: '#f0f0f0', overflow: 'hidden', margin: 0, padding: 0 }}>
        <img src="/images/SeattleSkyline.jpeg" alt="Seattle City Council Banner" className="banner-image" style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
      </div>

      <RepLookup />
    </>
  )
}

export default App

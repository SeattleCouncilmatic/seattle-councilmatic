import { Link } from 'react-router-dom'
import './NotFound.css'

export default function NotFound() {
  return (
    <main className="notfound-page">
      <div className="notfound-container">
        <p className="notfound-code">404</p>
        <h1 className="notfound-title">Page not found</h1>
        <p className="notfound-message">
          We couldn't find the page you were looking for. The link may be broken,
          or the page may have moved.
        </p>
        <Link to="/" className="notfound-home-link">← Back to This Week</Link>
      </div>
    </main>
  )
}

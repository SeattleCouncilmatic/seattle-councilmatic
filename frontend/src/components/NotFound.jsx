import { Link } from 'react-router-dom'
import './NotFound.css'

const VARIANTS = {
  legislation: {
    title: 'Legislation not found',
    message: "We couldn't find that piece of legislation. It may have been removed, or the link may be incorrect.",
    linkLabel: '← Back to recent legislation',
  },
  meeting: {
    title: 'Meeting not found',
    message: "We couldn't find that meeting. It may have been removed, or the link may be incorrect.",
    linkLabel: '← Back to upcoming meetings',
  },
}

const DEFAULT_VARIANT = {
  title: 'Page not found',
  message: "We couldn't find the page you were looking for. The link may be broken, or the page may have moved.",
  linkLabel: '← Back to This Week',
}

export default function NotFound({ kind }) {
  const v = VARIANTS[kind] ?? DEFAULT_VARIANT
  return (
    <main className="notfound-page">
      <div className="notfound-container">
        <p className="notfound-code">404</p>
        <h1 className="notfound-title">{v.title}</h1>
        <p className="notfound-message">{v.message}</p>
        <Link to="/" className="notfound-home-link">{v.linkLabel}</Link>
      </div>
    </main>
  )
}

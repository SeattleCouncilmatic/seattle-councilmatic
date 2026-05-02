import { Link } from 'react-router-dom'
import './NotFound.css'

const VARIANTS = {
  legislation: {
    title: 'Legislation not found',
    message: "We couldn't find that piece of legislation. It may have been removed, or the link may be incorrect.",
    linkLabel: '← Browse all legislation',
    linkTo: '/legislation',
  },
  event: {
    title: 'Event not found',
    message: "We couldn't find that event. It may have been removed, or the link may be incorrect.",
    linkLabel: '← Browse all events',
    linkTo: '/events',
  },
}

const DEFAULT_VARIANT = {
  title: 'Page not found',
  message: "We couldn't find the page you were looking for. The link may be broken, or the page may have moved.",
  linkLabel: '← Back to Home',
  linkTo: '/',
}

export default function NotFound({ kind }) {
  const v = VARIANTS[kind] ?? DEFAULT_VARIANT
  return (
    <div className="notfound-page">
      <div className="notfound-container">
        <p className="notfound-code">404</p>
        <h1 className="notfound-title">{v.title}</h1>
        <p className="notfound-message">{v.message}</p>
        <Link to={v.linkTo} className="notfound-home-link">{v.linkLabel}</Link>
      </div>
    </div>
  )
}

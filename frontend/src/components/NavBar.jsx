import { Link } from 'react-router-dom';
import './NavBar.css';

// Items with `to` use React Router (full-page surfaces); items with `href`
// are hash anchors that scroll to a homepage section. The hash items are
// stubs for sections that don't exist yet — wire them up as those sections
// ship, or convert to `to` paths if they grow into their own pages.
const NAV_ITEMS = [
  { label: 'This Week',          href: '#this-week' },
  { label: 'About',              href: '#about' },
  { label: 'How It Works',       href: '#how-it-works' },
  { label: 'Meetings',           href: '#meetings' },
  { label: 'Legislation',        to:   '/legislation' },
  { label: 'My Council Members', href: '#my-council-members' },
  { label: 'Glossary',           href: '#glossary' },
];

export default function NavBar({ activeItem = 'This Week' }) {
  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="navbar-inner">
        {NAV_ITEMS.map(({ label, href, to }) => {
          const className = `navbar-item${label === activeItem ? ' navbar-item--active' : ''}`;
          const ariaCurrent = label === activeItem ? 'page' : undefined;
          return to ? (
            <Link key={label} to={to} className={className} aria-current={ariaCurrent}>
              {label}
            </Link>
          ) : (
            <a key={label} href={href} className={className} aria-current={ariaCurrent}>
              {label}
            </a>
          );
        })}
      </div>
    </nav>
  );
}

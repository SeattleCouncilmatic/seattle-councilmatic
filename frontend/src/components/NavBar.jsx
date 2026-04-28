import { Link, useLocation } from 'react-router-dom';
import './NavBar.css';

// Items with `to` use React Router (full-page surfaces); items with `href`
// are hash anchors that scroll to a homepage section. The hash items are
// stubs for sections that don't exist yet — wire them up as those sections
// ship, or convert to `to` paths if they grow into their own pages.
const NAV_ITEMS = [
  { label: 'This Week',          href: '#this-week' },
  { label: 'About',              to:   '/about' },
  { label: 'How It Works',       href: '#how-it-works' },
  { label: 'Events',             to:   '/events' },
  { label: 'Legislation',        to:   '/legislation' },
  { label: 'Municode',           to:   '/municode' },
  { label: 'My Council Members', to:   '/reps' },
  { label: 'Glossary',           href: '#glossary' },
];

function isActive(pathname, item) {
  if (item.to) return pathname === item.to || pathname.startsWith(item.to + '/');
  // Hash items are only "active" on the homepage's This Week stub.
  if (item.label === 'This Week') return pathname === '/';
  return false;
}

export default function NavBar() {
  const { pathname } = useLocation();
  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="navbar-inner">
        {NAV_ITEMS.map((item) => {
          const { label, href, to } = item;
          const active = isActive(pathname, item);
          const className = `navbar-item${active ? ' navbar-item--active' : ''}`;
          const ariaCurrent = active ? 'page' : undefined;
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

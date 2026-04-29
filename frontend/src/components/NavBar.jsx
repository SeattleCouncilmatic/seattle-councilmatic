import { Link, useLocation } from 'react-router-dom';
import './NavBar.css';

const NAV_ITEMS = [
  { label: 'Home',               to: '/' },
  { label: 'About',              to: '/about' },
  { label: 'Events',             to: '/events' },
  { label: 'Legislation',        to: '/legislation' },
  { label: 'Municode',           to: '/municode' },
  { label: 'My Council Members', to: '/reps' },
];

function isActive(pathname, item) {
  // `Home` is active on `/` only — every path "starts with /", so the
  // generic prefix check would mark it active on every page.
  if (item.to === '/') return pathname === '/';
  return pathname === item.to || pathname.startsWith(item.to + '/');
}

export default function NavBar() {
  const { pathname } = useLocation();
  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="navbar-inner">
        {NAV_ITEMS.map((item) => {
          const { label, to } = item;
          const active = isActive(pathname, item);
          const className = `navbar-item${active ? ' navbar-item--active' : ''}`;
          const ariaCurrent = active ? 'page' : undefined;
          return (
            <Link key={label} to={to} className={className} aria-current={ariaCurrent}>
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

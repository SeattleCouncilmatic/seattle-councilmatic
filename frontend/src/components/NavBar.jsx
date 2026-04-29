import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import './NavBar.css';

const NAV_ITEMS = [
  { label: 'Home',         to: '/' },
  { label: 'About',        to: '/about' },
  { label: 'Events',       to: '/events' },
  { label: 'Legislation',  to: '/legislation' },
  { label: 'Municode',     to: '/municode' },
  { label: 'City Council', to: '/reps' },
];

function isActive(pathname, item) {
  // `Home` is active on `/` only — every path "starts with /", so the
  // generic prefix check would mark it active on every page.
  if (item.to === '/') return pathname === '/';
  return pathname === item.to || pathname.startsWith(item.to + '/');
}

export default function NavBar() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);

  // Close the menu on navigation (covers the "click an item" case) and
  // on Escape. No outside-click handler — closing on path change covers
  // the common dismissal flow, and the open menu doesn't trap focus.
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <nav className="navbar" aria-label="Main Navigation">
      <button
        type="button"
        className="navbar-toggle"
        aria-expanded={open}
        aria-controls="navbar-items"
        aria-label={open ? 'Close menu' : 'Open menu'}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <X size={24} aria-hidden="true" /> : <Menu size={24} aria-hidden="true" />}
      </button>
      <div
        id="navbar-items"
        className={`navbar-inner${open ? ' navbar-inner--open' : ''}`}
      >
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

import './NavBar.css';

const NAV_ITEMS = [
  { label: 'This Week',         href: '#this-week' },
  { label: 'About',             href: '#about' },
  { label: 'How It Works',      href: '#how-it-works' },
  { label: 'Meetings',          href: '#meetings' },
  { label: 'Legislation',       href: '#legislation' },
  { label: 'My Council Members', href: '#my-council-members' },
  { label: 'Glossary',          href: '#glossary' },
];

export default function NavBar({ activeItem = 'This Week' }) {
  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="navbar-inner">
        {NAV_ITEMS.map(({ label, href }) => (
          <a
            key={label}
            href={href}
            className={`navbar-item${label === activeItem ? ' navbar-item--active' : ''}`}
            aria-current={label === activeItem ? 'page' : undefined}
          >
            {label}
          </a>
        ))}
      </div>
    </nav>
  );
}

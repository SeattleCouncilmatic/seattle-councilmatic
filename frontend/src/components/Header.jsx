import { Link } from 'react-router-dom';
import NavBar from './NavBar';

export default function Header() {
  return (
    <header className="header">
      <div className="header-container">
        <div className="header-content">

          {/* Logo + title — clickable, returns to homepage from any page.
              The favicon image is decorative (alt=""); the parent
              <Link>'s aria-label carries the link's purpose. */}
          <Link to="/" className="logo-section" aria-label="Seattle Councilmatic — Home">

            <img src="/favicon.png" alt="" className="logo-icon-img" />

            <div>
              <h1 className="title">Seattle Councilmatic</h1>
              <p className="subtitle">
                An easy way to follow Seattle City Council activity and find local bills.
              </p>
            </div>
          </Link>

          <NavBar />
        </div>
      </div>
    </header>
  );
}
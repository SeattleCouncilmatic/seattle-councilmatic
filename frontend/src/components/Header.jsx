import { Link } from 'react-router-dom';
import { Landmark } from 'lucide-react';
import NavBar from './NavBar';

export default function Header() {
  return (
    <header className="header">
      <div className="header-container">
        <div className="header-content">

          {/* Logo + title — clickable, returns to homepage from any page */}
          <Link to="/" className="logo-section" aria-label="Seattle Councilmatic — Home">

            {/* logo icon */}
            <div className="logo-icon">
              <Landmark className="icon" strokeWidth={2.5} />
            </div>

            {/* title and subtitle */}
            <div>
              {/* Branding wordmark, not a heading — using <p> so each
                  page's actual <h1> (bill identifier, section number,
                  rep name, etc.) is the only h1 in the document. */}
              <p className="title">Seattle Councilmatic</p>
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
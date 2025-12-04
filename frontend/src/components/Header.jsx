import { Landmark } from 'lucide-react';

export default function Header() {
  return (
    <header className="header">
      <div className="header-container">
        <div className="header-content">
          
          {/* logo and title */}
          <div className="logo-section">
            
            {/* logo icon */}
            <div className="logo-icon">
              <Landmark className="icon" strokeWidth={2.5} />
            </div>
            
            {/* title and subtitle */}
            <div>
              <h1 className="title">Seattle Councilmatic</h1>
              <p className="subtitle">
                An easy way to follow Seattle City Council activity and find local bills.
              </p>
            </div>
          </div>
          
        </div>
      </div>
    </header>
  );
}
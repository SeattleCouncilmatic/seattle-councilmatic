import './Footer.css'

const REPO_URL = 'https://github.com/SeattleCouncilmatic/seattle-councilmatic'
const COUNCILMATIC_URL = 'https://councilmatic.org/'

export default function Footer() {
  const year = new Date().getFullYear()
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <p className="site-footer-copyright">© {year} Seattle Councilmatic</p>
        <div className="site-footer-links">
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
          <span className="site-footer-sep" aria-hidden="true">·</span>
          <span>
            Part of the{' '}
            <a href={COUNCILMATIC_URL} target="_blank" rel="noopener noreferrer">
              Councilmatic
            </a>
            {' '}Family
          </span>
        </div>
      </div>
    </footer>
  )
}

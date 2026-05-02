import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import NotFound from './NotFound'
import SectionText from './SectionText'
import { Breadcrumb, LoadingView, ErrorView } from './MuniCodeTitle'
import './MuniCodeDetail.css'

export default function MuniCodeAppendix() {
  const { title, label } = useParams()

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)

  useEffect(() => {
    setData(null); setError(null); setStatus(null)
    fetch(`/api/smc/appendices/${encodeURIComponent(title)}/${encodeURIComponent(label)}/`)
      .then(r => {
        setStatus(r.status)
        if (r.status === 404) return null
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setError(e.message))
  }, [title, label])

  if (status === 404) return <NotFound />
  if (error) return <ErrorView msg={error} />
  if (!data) return <LoadingView />

  return (
    <div className="smc-detail-page">
      <div className="smc-detail-container">
        <Breadcrumb crumbs={[
          { to: '/', label: 'Home' },
          { to: '/municode', label: 'Municipal Code' },
          { to: `/municode/${data.title_number}`, label: `Title ${data.title_number}` },
          { current: `Appendix ${data.label}` },
        ]} />
        <header className="smc-detail-header">
          <h1 className="smc-detail-h1">Title {data.title_number} — Appendix {data.label}</h1>
        </header>

        <section className="smc-section-body" aria-label="Appendix text">
          <SectionText text={data.full_text} />
        </section>

        {data.source_pdf_page && (
          <p className="smc-source-note">
            Source: Seattle Municipal Code, PDF page {data.source_pdf_page}.
          </p>
        )}
      </div>
    </div>
  )
}

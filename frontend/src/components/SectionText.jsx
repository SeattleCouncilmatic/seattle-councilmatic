import BillLinkify from './BillLinkify'
import './SectionText.css'

// SMC body text comes out of the parser hard-wrapped at PDF column width
// (each line ~50 chars, broken mid-sentence). The legal structure lives in
// enumeration markers — A./B./C. for top-level items, 1./2./3. nested,
// a./b./c. one deeper. Light pass: reflow lines into paragraphs by joining
// non-marker lines with spaces, start a fresh paragraph on each marker
// line, and indent by marker level.
const ENUM_RE = /^([A-Z]\.|[a-z]\.|\d+\.)\s+/

function markerLevel(marker) {
  if (!marker) return 0
  if (/^[A-Z]\./.test(marker)) return 1
  if (/^\d+\./.test(marker)) return 2
  return 3 // lowercase
}

function reflow(text) {
  if (!text) return []
  const lines = text.split('\n')
  const paragraphs = []
  let buf = []
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      if (buf.length) {
        paragraphs.push(buf.join(' '))
        buf = []
      }
      continue
    }
    if (ENUM_RE.test(line) && buf.length > 0) {
      paragraphs.push(buf.join(' '))
      buf = [line]
    } else {
      buf.push(line)
    }
  }
  if (buf.length) paragraphs.push(buf.join(' '))

  return paragraphs.map((p) => {
    const m = p.match(ENUM_RE)
    if (m) {
      return { marker: m[1], rest: p.slice(m[0].length), level: markerLevel(m[1]) }
    }
    return { marker: null, rest: p, level: 0 }
  })
}

export default function SectionText({ text, billRefs }) {
  const paragraphs = reflow(text)
  if (paragraphs.length === 0) {
    return <p className="smc-text-empty">No body text available for this section.</p>
  }
  return (
    <div className="smc-text">
      {paragraphs.map((p, i) => (
        <p key={i} className={`smc-text-p smc-text-l${p.level}`}>
          {p.marker && <span className="smc-text-marker">{p.marker}</span>}
          {p.marker ? ' ' : null}
          <BillLinkify text={p.rest} refs={billRefs} />
        </p>
      ))}
    </div>
  )
}

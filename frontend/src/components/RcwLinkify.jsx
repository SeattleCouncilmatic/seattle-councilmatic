import './RcwLinkify.css'

// Matches RCW citations like "RCW 35.21.560", "RCW 36.70A.040",
// "RCW 9A.36.041", or chapter-only "RCW 35.21" / "RCW 36.70A".
// Letter suffixes appear on either the title segment (9A.36.041
// — criminal code) or the chapter segment (36.70A.040 — Growth
// Management Act); we allow them on any numeric segment to keep
// the regex simple. Third segment optional → chapter-level link.
const RCW_RE = /\bRCW\s+(\d+[A-Z]?\.\d+[A-Z]?(?:\.\d+[A-Z]?)?)\b/g

function rcwUrl(cite) {
  return `https://app.leg.wa.gov/RCW/default.aspx?cite=${cite}`
}

// Inline replacer: scans `text` for RCW cites and renders each
// match as an external link, leaving surrounding text untouched.
// Returns a Fragment so the caller can drop it directly inside
// any block element (<p>, <li>, etc.) without changing the DOM
// shape they already expect for plain strings.
export default function RcwLinkify({ text }) {
  if (!text) return null
  const parts = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(RCW_RE)) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const cite = m[1]
    parts.push(
      <a
        key={key++}
        href={rcwUrl(cite)}
        target="_blank"
        rel="noopener noreferrer"
        className="rcw-ref"
      >
        RCW {cite}
        <span className="rcw-ref-arrow" aria-hidden="true">↗</span>
      </a>
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

import './RcwLinkify.css'

// RCW citations appear in three shapes across SMC + bill text:
//
//   1. Prefix:  "RCW 35.21.560"  (canonical)
//   2. Suffix:  "19.405 RCW"     (legal-drafting style — common in
//               bill text where the chapter is named first)
//   3. Verbose: "Chapter 35.79 of the Revised Code of Washington"
//               (and "Section X.Y.Z of the Revised Code of Washington")
//
// The cite token allows an optional uppercase letter suffix on any
// segment to cover both letter-suffix titles (9A.36.041 — criminal
// code) and letter-suffix chapters (36.70A.040 — Growth Management
// Act). The third segment is optional so chapter-level refs link to
// the chapter page rather than a section.
//
// Branches are wrapped in a single regex with three capturing groups
// (one per branch); only one fires per match, so we OR them together
// when reading the cite below. Case-insensitive so verbose-form
// connectors ("Chapter", "Section", "of the Revised Code of
// Washington") match regardless of casing in the source text.
const CITE = '\\d+[A-Z]?\\.\\d+[A-Z]?(?:\\.\\d+[A-Z]?)?'
const RCW_RE = new RegExp(
  '\\b(?:' +
    'RCW\\s+(' + CITE + ')' +
  '|' +
    '(' + CITE + ')\\s+RCW' +
  '|' +
    '(?:Chapter|Section)\\s+(' + CITE + ')\\s+of\\s+the\\s+Revised\\s+Code\\s+of\\s+Washington' +
  ')\\b',
  'gi',
)

function rcwUrl(cite) {
  return `https://app.leg.wa.gov/RCW/default.aspx?cite=${cite}`
}

// Inline replacer: scans `text` for RCW cites in any of the three
// supported shapes and renders each match as an external link,
// preserving the original surface form as the link text. Surrounding
// text passes through untouched. Returns a Fragment so the caller
// can drop it directly inside any block element (<p>, <li>, etc.)
// without changing the DOM shape they already expect for plain
// strings.
export default function RcwLinkify({ text }) {
  if (!text) return null
  const parts = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(RCW_RE)) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const cite = m[1] || m[2] || m[3]
    parts.push(
      <a
        key={key++}
        href={rcwUrl(cite)}
        target="_blank"
        rel="noopener noreferrer"
        className="rcw-ref"
      >
        {m[0]}
        <span className="rcw-ref-arrow" aria-hidden="true">↗</span>
      </a>,
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

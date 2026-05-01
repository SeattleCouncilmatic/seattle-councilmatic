import { Link } from 'react-router-dom'
import RcwLinkify from './RcwLinkify'
import './BillLinkify.css'

// Match prose citations of the form "CB 121185", "Resolution 32195",
// "Res. 32168", "Ordinance 127362", "Ord. 127400". Mirrors the server
// regex in seattle_app/services/prose_refs.py — keep them in sync.
// Case-insensitive to accommodate LLM output variations; `\.?` after
// the prefix lets us pick up "Ord. " and "Ord " forms; `\s+` requires
// whitespace before the number.
const BILL_RE = /\b(CB|Res(?:olution)?|Ord(?:inance)?)\.?\s+(\d+)\b/gi

// Wraps text and renders any matched bill citation as a <Link> when
// the cite resolves in `refs` (a `{kind:num -> slug}` map produced by
// the API), or plain text when it doesn't. Plain-text segments
// (between matches OR for unresolved cites) are recursively passed
// through RcwLinkify so RCW citations in the same prose still get
// their external links.
//
// Pass refs={bill.bill_refs} from a legislation/SMC detail response.
// When refs is omitted the component degrades to "plain text + RCW
// linkify only" — same shape as RcwLinkify alone.
export default function BillLinkify({ text, refs }) {
  if (!text) return null
  const lookup = refs || {}
  const parts = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(BILL_RE)) {
    if (m.index > last) {
      parts.push(<RcwLinkify key={key++} text={text.slice(last, m.index)} />)
    }
    const kind = m[1].slice(0, 3).toLowerCase()
    const slug = lookup[`${kind}:${m[2]}`]
    if (slug) {
      parts.push(
        <Link
          key={key++}
          to={`/legislation/${slug}`}
          className="bill-ref"
        >
          {m[0]}
        </Link>,
      )
    } else {
      parts.push(m[0])
    }
    last = m.index + m[0].length
  }
  if (last < text.length) {
    parts.push(<RcwLinkify key={key++} text={text.slice(last)} />)
  }
  return <>{parts}</>
}

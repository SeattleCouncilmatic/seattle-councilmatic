import BillLinkify from './BillLinkify'
import './SectionText.css'

// SMC body text comes out of the parser hard-wrapped at PDF column width
// (each line ~50 chars, broken mid-sentence). The legal structure lives in
// enumeration markers — A./B./C. for top-level items, 1./2./3. nested,
// a./b./c. one deeper. Light pass: reflow lines into paragraphs by joining
// non-marker lines with spaces, start a fresh paragraph on each marker
// line, and indent by marker level.
const ENUM_RE = /^([A-Z]\.|[a-z]\.|\d+\.)\s+/

// Markdown table row: starts and ends with `|`. The parser/extractor
// emits these for the SMC's rate, dimensional, license, and use-permission
// tables (~125 sections after extract_smc_tables runs). Without dedicated
// rendering they leak through as literal pipe characters.
const TABLE_ROW_RE = /^\s*\|.*\|\s*$/
// Separator row: every cell is `---` or `:---:` etc. Splits header from body.
const TABLE_SEP_CELL_RE = /^:?-+:?$/
// Italics for table footnotes (extract_smc_tables emits these as
// `_text_` lines just below the table). Render as <em> paragraphs.
const FOOTNOTE_RE = /^_(.+)_\s*$/

function markerLevel(marker) {
  if (!marker) return 0
  if (/^[A-Z]\./.test(marker)) return 1
  if (/^\d+\./.test(marker)) return 2
  return 3 // lowercase
}

function parseTableRow(line) {
  // Strip optional leading/trailing pipes, split on `|`, trim each cell.
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((c) => c.trim())
}

function isSeparatorRow(cells) {
  return cells.length > 0 && cells.every((c) => TABLE_SEP_CELL_RE.test(c))
}

function finalizeTable(rows) {
  // Locate separator row to split header/body. Rows before it are header
  // (extract_smc_tables emits caption row + column-header row); rows after
  // are body. With no separator, render everything as body.
  const sepIdx = rows.findIndex(isSeparatorRow)
  if (sepIdx < 0) {
    return { type: 'table', header: [], body: rows }
  }
  return {
    type: 'table',
    header: rows.slice(0, sepIdx),
    body: rows.slice(sepIdx + 1),
  }
}

function finalizeParagraph(buf) {
  const text = buf.join(' ')
  const m = text.match(ENUM_RE)
  if (m) {
    return {
      type: 'p',
      marker: m[1],
      rest: text.slice(m[0].length),
      level: markerLevel(m[1]),
    }
  }
  return { type: 'p', marker: null, rest: text, level: 0 }
}

function blockify(text) {
  if (!text) return []
  const lines = text.split('\n')
  const blocks = []
  let paraBuf = []
  let tableBuf = []

  const flushPara = () => {
    if (paraBuf.length) {
      blocks.push(finalizeParagraph(paraBuf))
      paraBuf = []
    }
  }
  const flushTable = () => {
    if (tableBuf.length) {
      blocks.push(finalizeTable(tableBuf))
      tableBuf = []
    }
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (TABLE_ROW_RE.test(line)) {
      flushPara()
      tableBuf.push(parseTableRow(line))
      continue
    }
    flushTable()
    if (!line) {
      flushPara()
      continue
    }
    const fnMatch = line.match(FOOTNOTE_RE)
    if (fnMatch) {
      flushPara()
      blocks.push({ type: 'footnote', text: fnMatch[1] })
      continue
    }
    if (ENUM_RE.test(line) && paraBuf.length > 0) {
      flushPara()
      paraBuf.push(line)
    } else {
      paraBuf.push(line)
    }
  }
  flushTable()
  flushPara()
  return blocks
}

function Table({ header, body, billRefs }) {
  return (
    <div className="smc-text-table-wrap" tabIndex={0} role="region" aria-label="Data table">
      <table className="smc-text-table">
        {header.length > 0 && (
          <thead>
            {header.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <th key={j}>
                    <BillLinkify text={cell} refs={billRefs} />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
        )}
        <tbody>
          {body.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>
                  <BillLinkify text={cell} refs={billRefs} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function SectionText({ text, billRefs }) {
  const blocks = blockify(text)
  if (blocks.length === 0) {
    return <p className="smc-text-empty">No body text available for this section.</p>
  }
  return (
    <div className="smc-text">
      {blocks.map((b, i) => {
        if (b.type === 'table') {
          return <Table key={i} header={b.header} body={b.body} billRefs={billRefs} />
        }
        if (b.type === 'footnote') {
          return (
            <p key={i} className="smc-text-footnote">
              <BillLinkify text={b.text} refs={billRefs} />
            </p>
          )
        }
        return (
          <p key={i} className={`smc-text-p smc-text-l${b.level}`}>
            {b.marker && <span className="smc-text-marker">{b.marker}</span>}
            {b.marker ? ' ' : null}
            <BillLinkify text={b.rest} refs={billRefs} />
          </p>
        )
      })}
    </div>
  )
}

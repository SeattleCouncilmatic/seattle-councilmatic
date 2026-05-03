import { useId, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import './LegislationInvolvementTable.css'

const PAGE_SIZE = 25

// Columns we expose to sort. Default order from the server is
// `latest_action_date` desc, which we surface as the "Date" column —
// not visible in the table but is the implicit primary sort key.
// `null` comparator means "use server order"; clicking another header
// switches to a per-column comparator.
const COLUMNS = [
  { key: 'bill',           label: 'Bill',           sortable: true,  scope: 'col' },
  { key: 'status',         label: 'Status',         sortable: true,  scope: 'col' },
  { key: 'sponsorship',    label: 'Sponsorship',    sortable: true,  scope: 'col' },
  { key: 'committee_vote', label: 'Committee vote', sortable: true,  scope: 'col' },
  { key: 'council_vote',   label: 'Council vote',   sortable: true,  scope: 'col' },
  { key: 'outcome',        label: 'Outcome',        sortable: true,  scope: 'col' },
]

// Vote/sponsorship/outcome cell values are sorted by a stable rank so
// e.g. "Yes" rows cluster together and "—" rows go to the end. Lower
// number = appears first in ascending order.
const SPONSORSHIP_RANK = { primary: 0, cosponsor: 1, null: 2 }
const VOTE_OPTION_RANK = {
  yes: 0, no: 1, abstain: 2, absent: 3, excused: 4, 'not voting': 5, other: 6, null: 7,
}
const OUTCOME_RANK = { pass: 0, fail: 1, null: 2 }

function compareRows(a, b, key, dir) {
  const sign = dir === 'asc' ? 1 : -1
  switch (key) {
    case 'bill':
      return sign * a.bill.identifier.localeCompare(b.bill.identifier, 'en', { numeric: true })
    case 'status':
      return sign * a.status.label.localeCompare(b.status.label)
    case 'sponsorship': {
      const ra = SPONSORSHIP_RANK[a.sponsorship ?? 'null']
      const rb = SPONSORSHIP_RANK[b.sponsorship ?? 'null']
      return sign * (ra - rb)
    }
    case 'committee_vote': {
      const ra = VOTE_OPTION_RANK[a.committee_vote?.option ?? 'null']
      const rb = VOTE_OPTION_RANK[b.committee_vote?.option ?? 'null']
      return sign * (ra - rb)
    }
    case 'council_vote': {
      const ra = VOTE_OPTION_RANK[a.council_vote?.option ?? 'null']
      const rb = VOTE_OPTION_RANK[b.council_vote?.option ?? 'null']
      return sign * (ra - rb)
    }
    case 'outcome': {
      const ra = OUTCOME_RANK[a.outcome ?? 'null']
      const rb = OUTCOME_RANK[b.outcome ?? 'null']
      return sign * (ra - rb)
    }
    default:
      return 0
  }
}

function VoteCell({ vote, extraCount, billSlug }) {
  if (!vote) return <span className="involvement-cell-empty" aria-label="No vote">—</span>
  const optClass = vote.option.replace(/\s+/g, '-')
  return (
    <div className="involvement-vote-cell">
      <span className={`involvement-vote-chip involvement-vote-chip--${optClass}`}>
        {vote.option_label}
      </span>
      {vote.body_name && (
        <span className="involvement-vote-body">{vote.body_name}</span>
      )}
      {extraCount > 0 && (
        <Link
          to={`/legislation/${billSlug}/`}
          className="involvement-vote-extra"
          aria-label={`+${extraCount} earlier committee vote${extraCount === 1 ? '' : 's'} on ${billSlug} — view full roll-call`}
        >
          +{extraCount} earlier
        </Link>
      )}
    </div>
  )
}

export default function LegislationInvolvementTable({ rows, repName }) {
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState(null) // null = server order
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(1)
  const searchId = useId()
  const liveRegionId = useId()

  // Filter (case-insensitive on identifier + title).
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(r =>
      r.bill.identifier.toLowerCase().includes(q) ||
      r.bill.title.toLowerCase().includes(q)
    )
  }, [rows, query])

  // Sort (in-place copy when a sort key is active; otherwise keep server order).
  const sorted = useMemo(() => {
    if (!sortKey) return filtered
    return [...filtered].sort((a, b) => compareRows(a, b, sortKey, sortDir))
  }, [filtered, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const start = (safePage - 1) * PAGE_SIZE
  const pageRows = sorted.slice(start, start + PAGE_SIZE)

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
    setPage(1)
  }

  function ariaSort(key) {
    if (sortKey !== key) return 'none'
    return sortDir === 'asc' ? 'ascending' : 'descending'
  }

  return (
    <div className="involvement-table-wrap">
      <div className="involvement-toolbar">
        <label htmlFor={searchId} className="involvement-search-label">
          Filter bills
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={e => { setQuery(e.target.value); setPage(1) }}
          placeholder="Bill number or title…"
          className="involvement-search-input"
        />
        <span className="involvement-toolbar-meta" id={liveRegionId} aria-live="polite">
          {sorted.length === rows.length
            ? `${rows.length.toLocaleString()} bills`
            : `${sorted.length.toLocaleString()} of ${rows.length.toLocaleString()} bills`}
        </span>
      </div>

      {sorted.length === 0 ? (
        <p className="involvement-empty" role="status">
          No bills match <strong>{query}</strong>.
        </p>
      ) : (
        <>
          <div className="involvement-table-scroll" role="region" aria-label="Legislation involvement table" tabIndex={0}>
            <table className="involvement-table">
              <caption className="sr-only">
                Bills {repName} has sponsored or voted on
              </caption>
              <thead>
                <tr>
                  {COLUMNS.map(col => (
                    <th key={col.key} scope={col.scope} aria-sort={ariaSort(col.key)}>
                      {col.sortable ? (
                        <button
                          type="button"
                          className="involvement-th-button"
                          onClick={() => handleSort(col.key)}
                        >
                          {col.label}
                          <span aria-hidden="true" className="involvement-sort-indicator">
                            {sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                          </span>
                        </button>
                      ) : col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map(row => (
                  <tr key={row.bill.slug}>
                    <th scope="row" className="involvement-cell-bill">
                      <Link
                        to={`/legislation/${row.bill.slug}/`}
                        className="involvement-bill-link"
                        title={row.bill.title}
                      >
                        {row.bill.identifier}
                      </Link>
                    </th>
                    <td>
                      <span className={`involvement-status-chip involvement-status-chip--${row.status.variant}`}>
                        {row.status.label}
                      </span>
                    </td>
                    <td>
                      {row.sponsorship === 'primary' && (
                        <span className="involvement-sponsor-chip involvement-sponsor-chip--primary">
                          Primary
                        </span>
                      )}
                      {row.sponsorship === 'cosponsor' && (
                        <span className="involvement-sponsor-chip involvement-sponsor-chip--cosponsor">
                          Cosponsor
                        </span>
                      )}
                      {!row.sponsorship && (
                        <span className="involvement-cell-empty" aria-label="Not a sponsor">—</span>
                      )}
                    </td>
                    <td>
                      <VoteCell
                        vote={row.committee_vote}
                        extraCount={row.extra_committee_votes}
                        billSlug={row.bill.slug}
                      />
                    </td>
                    <td>
                      <VoteCell vote={row.council_vote} extraCount={0} billSlug={row.bill.slug} />
                    </td>
                    <td>
                      {row.outcome === 'pass' && (
                        <span className="involvement-outcome involvement-outcome--pass">Pass</span>
                      )}
                      {row.outcome === 'fail' && (
                        <span className="involvement-outcome involvement-outcome--fail">Fail</span>
                      )}
                      {!row.outcome && (
                        <span className="involvement-cell-empty" aria-label="No vote outcome">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <nav className="involvement-pagination" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={safePage === 1}
                className="involvement-page-button"
              >
                ← Previous
              </button>
              <span className="involvement-page-status">
                Page {safePage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={safePage === totalPages}
                className="involvement-page-button"
              >
                Next →
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}

import { Link } from 'react-router-dom'
import './NeighborNav.css'

// Renders prev/next pills for sequential navigation. `neighbors` shape:
//   { prev: {primary, secondary?, path} | null,
//     next: {primary, secondary?, path} | null }
// Both slots are always rendered so the layout stays balanced; missing
// neighbors render as a disabled placeholder.
export default function NeighborNav({ neighbors, ariaLabel = 'Sequential navigation' }) {
  if (!neighbors) return null
  const { prev, next } = neighbors
  return (
    <nav className="smc-neighbor-nav" aria-label={ariaLabel}>
      <NeighborSlot side="prev" item={prev} />
      <NeighborSlot side="next" item={next} />
    </nav>
  )
}

function NeighborSlot({ side, item }) {
  const arrow = side === 'prev' ? '←' : '→'
  const label = side === 'prev' ? 'Previous' : 'Next'

  if (!item) {
    return (
      <div className={`smc-neighbor smc-neighbor--${side} smc-neighbor--empty`} aria-hidden="true">
        <span className="smc-neighbor-arrow">{arrow}</span>
        <span className="smc-neighbor-text">
          <span className="smc-neighbor-label">{label}</span>
          <span className="smc-neighbor-primary">—</span>
        </span>
      </div>
    )
  }
  return (
    <Link to={item.path} className={`smc-neighbor smc-neighbor--${side}`}>
      <span className="smc-neighbor-arrow">{arrow}</span>
      <span className="smc-neighbor-text">
        <span className="smc-neighbor-label">{label}</span>
        <span className="smc-neighbor-primary">{item.primary}</span>
        {item.secondary && <span className="smc-neighbor-secondary">{item.secondary}</span>}
      </span>
    </Link>
  )
}

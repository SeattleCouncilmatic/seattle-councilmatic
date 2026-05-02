import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { DISTRICT_COLORS } from './districtColors'
import './DistrictMiniMap.css'

// Close-up of a single district — rendered on /reps/district/<n>/. Sister
// to CouncilMap (which shows all 7 with click-through behavior). This one
// is non-interactive: no scroll-zoom, no click-to-navigate; it's purely
// "here's the area you're looking at."
export default function DistrictMiniMap({ geometry, districtNumber }) {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)

  useEffect(() => {
    if (!mapRef.current || !geometry) return

    if (!mapInstanceRef.current) {
      mapInstanceRef.current = L.map(mapRef.current, {
        center: [47.6062, -122.3321],
        zoom: 11,
        zoomControl: true,
        scrollWheelZoom: false,
        // Same rationale as CouncilMap: Leaflet's built-in
        // attribution control trips Firefox's "clickable but not
        // focusable" check. Render the OSM/CARTO links as plain
        // HTML below the map instead.
        attributionControl: false,
      })
      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 20,
      }).addTo(mapInstanceRef.current)
    }

    // Replace any existing district layer
    mapInstanceRef.current.eachLayer((layer) => {
      if (layer instanceof L.GeoJSON) {
        mapInstanceRef.current.removeLayer(layer)
      }
    })

    const color = DISTRICT_COLORS[districtNumber] || '#2E3D5B'
    const layer = L.geoJSON(geometry, {
      style: {
        color,
        weight: 3,
        opacity: 1,
        fillColor: color,
        fillOpacity: 0.35,
      },
    }).addTo(mapInstanceRef.current)

    // Defer fitBounds + invalidateSize to the next paint so Leaflet
    // measures the container after the browser has finished layout.
    // Without this, the map can render at 0×0 if the parent's height
    // hasn't been computed yet on first mount.
    requestAnimationFrame(() => {
      if (!mapInstanceRef.current) return
      mapInstanceRef.current.invalidateSize()
      mapInstanceRef.current.fitBounds(layer.getBounds(), { padding: [20, 20] })
    })
  }, [geometry, districtNumber])

  useEffect(() => {
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
        mapInstanceRef.current = null
      }
    }
  }, [])

  if (!geometry) return null
  return (
    <div className="district-mini-map-wrapper">
      <div
        ref={mapRef}
        className="district-mini-map"
        role="img"
        aria-label={`Boundary of District ${districtNumber}`}
      />
      <p className="district-mini-map-attribution">
        Map &copy;{' '}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">
          OpenStreetMap
        </a>
        {' '}contributors &copy;{' '}
        <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">
          CARTO
        </a>
      </p>
    </div>
  )
}

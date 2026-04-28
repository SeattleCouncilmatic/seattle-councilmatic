import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './CouncilMap.css'

// One distinguishable colour per district. Tab10 palette for D1-D6, the
// site brand navy for D7 so it sits next to the rest visually.
const DISTRICT_COLORS = {
  '1': '#1f77b4', // blue
  '2': '#ff7f0e', // orange
  '3': '#2ca02c', // green
  '4': '#d62728', // red
  '5': '#9467bd', // purple
  '6': '#8c564b', // brown
  '7': '#2E3D5B', // site navy
}

export default function CouncilMap({ districts }) {
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!mapRef.current || !districts || districts.length === 0) return

    if (!mapInstanceRef.current) {
      mapInstanceRef.current = L.map(mapRef.current, {
        center: [47.6062, -122.3321], // Seattle center
        zoom: 11,
        zoomControl: true,
        scrollWheelZoom: false,
      })

      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20,
      }).addTo(mapInstanceRef.current)
    }

    // Clear any existing district layers
    mapInstanceRef.current.eachLayer((layer) => {
      if (layer instanceof L.GeoJSON) {
        mapInstanceRef.current.removeLayer(layer)
      }
    })

    const allBounds = L.latLngBounds([])

    for (const d of districts) {
      if (!d.geometry) continue
      const color = DISTRICT_COLORS[d.number] || '#666'
      const layer = L.geoJSON(d.geometry, {
        style: {
          color,
          weight: 2,
          opacity: 0.9,
          fillColor: color,
          fillOpacity: 0.3,
        },
        onEachFeature: (_feature, lyr) => {
          const repName = d.rep?.name ?? 'Vacant'
          const repSlug = d.rep?.slug
          lyr.bindTooltip(
            `<strong>${d.name}</strong><br/>${repName}`,
            { sticky: true, direction: 'top' }
          )
          lyr.on('mouseover', () => {
            lyr.setStyle({ weight: 3, fillOpacity: 0.5 })
          })
          lyr.on('mouseout', () => {
            lyr.setStyle({ weight: 2, fillOpacity: 0.3 })
          })
          if (repSlug) {
            lyr.on('click', () => navigate(`/reps/${repSlug}`))
          }
        },
      }).addTo(mapInstanceRef.current)
      allBounds.extend(layer.getBounds())
    }

    if (allBounds.isValid()) {
      mapInstanceRef.current.fitBounds(allBounds, { padding: [16, 16] })
    }

    return () => {
      // Don't remove the map on every effect run; districts changing
      // re-renders polygons via the eachLayer cleanup above. Cleanup the
      // whole map only when the component unmounts.
    }
  }, [districts, navigate])

  // Full unmount cleanup
  useEffect(() => {
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
        mapInstanceRef.current = null
      }
    }
  }, [])

  return (
    <div className="council-map-wrapper">
      <div ref={mapRef} className="council-map" />
      <ul className="council-map-legend" aria-label="District legend">
        {Object.entries(DISTRICT_COLORS).map(([num, color]) => (
          <li key={num} className="council-map-legend-item">
            <span className="council-map-legend-swatch" style={{ background: color }} />
            District {num}
          </li>
        ))}
      </ul>
    </div>
  )
}

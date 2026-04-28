import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { DISTRICT_COLORS } from './districtColors'
import './CouncilMap.css'

export default function CouncilMap({ districts, onDistrictHover }) {
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
          lyr.bindTooltip(
            `<strong>${d.name}</strong><br/>${repName}`,
            { sticky: true, direction: 'top' }
          )
          lyr.on('mouseover', () => {
            lyr.setStyle({ weight: 3, fillOpacity: 0.5 })
            onDistrictHover?.(d.number)
          })
          lyr.on('mouseout', () => {
            lyr.setStyle({ weight: 2, fillOpacity: 0.3 })
            onDistrictHover?.(null)
          })
          // Click goes to the district page (rep + at-large), not straight
          // to the district rep — gives users the full picture of who
          // represents them before drilling into a single profile.
          lyr.on('click', () => navigate(`/reps/district/${d.number}`))
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

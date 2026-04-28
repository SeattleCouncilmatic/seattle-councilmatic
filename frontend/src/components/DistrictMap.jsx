import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './DistrictMap.css';

export default function DistrictMap({ geometry }) {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current || !geometry) return;

    // Initialize map if it doesn't exist
    if (!mapInstanceRef.current) {
      mapInstanceRef.current = L.map(mapRef.current, {
        center: [47.6062, -122.3321], // Seattle center
        zoom: 11,
        zoomControl: true,
        scrollWheelZoom: false
      });

      // Carto Voyager basemap. We were using OSM's public tile server,
      // which 403s third-party app traffic per OSM's TOS. Carto is free
      // for civic-scale use, no API key, attribution required.
      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20,
      }).addTo(mapInstanceRef.current);
    }

    // Clear existing layers
    mapInstanceRef.current.eachLayer((layer) => {
      if (layer instanceof L.GeoJSON) {
        mapInstanceRef.current.removeLayer(layer);
      }
    });

    // Add district boundary
    const geoJsonLayer = L.geoJSON(geometry, {
      style: {
        color: '#667eea',
        weight: 3,
        opacity: 0.8,
        fillColor: '#667eea',
        fillOpacity: 0.2
      }
    }).addTo(mapInstanceRef.current);

    // Fit map to district bounds
    mapInstanceRef.current.fitBounds(geoJsonLayer.getBounds(), {
      padding: [20, 20]
    });

    // Cleanup on unmount
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [geometry]);

  if (!geometry) {
    return null;
  }

  return <div ref={mapRef} className="district-map" />;
}
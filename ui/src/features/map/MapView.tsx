import {
  Map as MapViewGL,
  Source,
  Layer,
  NavigationControl,
  type MapRef,
} from '@vis.gl/react-maplibre'
import type { StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState, useMemo, Component, type ReactNode } from 'react'
import { useApp } from '../../app/store'
import type { Appearance } from '../../shell/appearances'
import { geometry, type DrawMode, type Position } from './selection'
class MapBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false }
  static getDerivedStateFromError() {
    return { error: true }
  }
  render() {
    return this.state.error ? (
      <div className="empty">
        3D map unavailable. Enter coordinates or GeoJSON in the Request panel; all weather workflows
        remain available.
      </div>
    ) : (
      this.props.children
    )
  }
}
export function MapView({ appearance }: { appearance: Appearance }) {
  return (
    <MapBoundary>
      <WeatherMap appearance={appearance} />
    </MapBoundary>
  )
}
function WeatherMap({ appearance }: { appearance: Appearance }) {
  const ref = useRef<MapRef>(null)
  const host = useRef<HTMLDivElement>(null)
  const s = useApp()
  const [style, setStyle] = useState<StyleSpecification | null>(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState<DrawMode>('point')
  const [draw, setDraw] = useState(false)
  const [vertices, setVertices] = useState<Position[]>([])
  const [globe, setGlobe] = useState(false)
  const [terrain, setTerrain] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [camera, setCamera] = useState({
    longitude: -76.5,
    latitude: 42.44,
    zoom: 4,
    pitch: 0,
    bearing: 0,
  })
  useEffect(() => {
    const controller = new AbortController()
    fetch('https://tiles.openfreemap.org/styles/positron', { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw Error()
        return r.json()
      })
      .then(setStyle)
      .catch((e) => {
        if (e.name !== 'AbortError')
          setError('Basemap unavailable. Location selection remains usable.')
      })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (!host.current) return
    const resize = new ResizeObserver(() => ref.current?.resize())
    resize.observe(host.current)
    return () => resize.disconnect()
  }, [])
  useEffect(() => {
    if (loaded) {
      const map = ref.current?.getMap()
      map?.setProjection({ type: globe ? 'globe' : 'mercator' })
      map?.setTerrain(terrain ? { source: 'dem', exaggeration: 1 } : null)
    }
  }, [loaded, globe, terrain, style])
  const themed = useMemo<StyleSpecification>(() => {
    if (!style)
      return {
        version: 8,
        sources: {},
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': appearance.chrome.bg },
          },
        ],
      }
    const next = structuredClone(style)
    next.layers = next.layers.map((layer) => {
      if (layer.type === 'background')
        return { ...layer, paint: { ...layer.paint, 'background-color': appearance.chrome.bg } }
      if (layer.type === 'fill')
        return {
          ...layer,
          paint: {
            ...layer.paint,
            'fill-color': layer.id.includes('water')
              ? appearance.chrome.surfaceRaised
              : appearance.chrome.surface,
          },
        }
      if (layer.type === 'line')
        return { ...layer, paint: { ...layer.paint, 'line-color': appearance.chrome.border } }
      if (layer.type === 'symbol')
        return {
          ...layer,
          paint: {
            ...layer.paint,
            'text-color': appearance.chrome.textMuted,
            'text-halo-color': appearance.chrome.bg,
          },
        }
      return layer
    })
    return next
  }, [style, appearance])
  const locations = Array.isArray(s.draft.locations)
    ? s.draft.locations
    : 'lat' in s.draft.locations
      ? [s.draft.locations]
      : s.discovery?.locations || []
  const sources = (s.discovery?.candidates || [])
    .filter((c) => !c.source.provisional)
    .map((c) => c.source.location)
    .filter((p) => !!p)
  const links = {
    type: 'FeatureCollection' as const,
    features:
      locations.length === 1
        ? sources.map((p) => ({
            type: 'Feature' as const,
            geometry: {
              type: 'LineString' as const,
              coordinates: [
                [locations[0].lon, locations[0].lat],
                [p!.lon, p!.lat],
              ],
            },
            properties: {},
          }))
        : [],
  }
  function fitSelection() {
    if (locations.length === 1)
      ref.current?.flyTo({ center: [locations[0].lon, locations[0].lat], zoom: 8 })
    else if (locations.length > 1)
      ref.current?.fitBounds(
        [
          [Math.min(...locations.map((p) => p.lon)), Math.min(...locations.map((p) => p.lat))],
          [Math.max(...locations.map((p) => p.lon)), Math.max(...locations.map((p) => p.lat))],
        ],
        { padding: 50 },
      )
  }
  const points = {
    type: 'FeatureCollection' as const,
    features: [
      ...locations.map((p) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
        properties: { kind: 'requested' },
      })),
      ...sources.map((p) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [p!.lon, p!.lat] },
        properties: { kind: 'source' },
      })),
    ],
  }
  const outline =
    !Array.isArray(s.draft.locations) && 'coordinates' in s.draft.locations
      ? s.draft.locations
      : !Array.isArray(s.draft.locations) && 'west' in s.draft.locations
        ? {
            type: 'Polygon' as const,
            coordinates: [
              [
                [s.draft.locations.west, s.draft.locations.south],
                [s.draft.locations.east, s.draft.locations.south],
                [s.draft.locations.east, s.draft.locations.north],
                [s.draft.locations.west, s.draft.locations.north],
                [s.draft.locations.west, s.draft.locations.south],
              ],
            ],
          }
        : null
  function apply(points: Position[]) {
    try {
      s.edit({ locations: geometry(mode, points) })
      setDraw(false)
      setVertices([])
      setError('')
    } catch (e) {
      setError(String(e))
    }
  }
  return (
    <div className="map-page" ref={host}>
      <div className="map-toolbar">
        <select
          aria-label="Selection shape"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as DrawMode)
            setVertices([])
          }}
        >
          <option value="point">Point</option>
          <option value="points">Point list</option>
          <option value="bbox">Bounding box</option>
          <option value="polygon">Polygon</option>
        </select>
        <button
          aria-pressed={draw}
          onClick={() => {
            setDraw(!draw)
            setVertices([])
          }}
        >
          {draw ? 'Cancel drawing' : 'Select on map'}
        </button>
        {draw && (
          <>
            <button onClick={() => setVertices((v) => v.slice(0, -1))}>Undo vertex</button>
            <button onClick={() => apply(vertices)}>Finish ({vertices.length})</button>
          </>
        )}
        <button onClick={fitSelection} disabled={!locations.length}>
          Fit points
        </button>
        <span className="spacer" />
        <button onClick={() => setCamera((c) => ({ ...c, pitch: c.pitch ? 0 : 55 }))}>
          2D / 3D
        </button>
        <button aria-pressed={globe} onClick={() => setGlobe(!globe)}>
          Globe
        </button>
        <button aria-pressed={terrain} onClick={() => setTerrain(!terrain)}>
          Terrain
        </button>
      </div>
      {draw && (
        <div className="map-instruction">
          Click{' '}
          {mode === 'point'
            ? 'a location'
            : mode === 'bbox'
              ? 'two opposite corners'
              : 'to add vertices, then Finish'}
          . Coordinates/GeoJSON can also be entered in Request.
        </div>
      )}
      <MapViewGL
        ref={ref}
        {...camera}
        onMove={(e) => setCamera(e.viewState)}
        mapStyle={themed}
        onLoad={() => setLoaded(true)}
        onError={() =>
          setError('Some map tiles could not load. Weather requests are independent of map tiles.')
        }
        onClick={(e) => {
          if (!draw) return
          const next = [...vertices, [e.lngLat.lng, e.lngLat.lat] as Position]
          setVertices(next)
          if (mode === 'point' || (mode === 'bbox' && next.length === 2)) apply(next)
        }}
      >
        <NavigationControl />
        <Source
          id="hillshade-dem"
          type="raster-dem"
          tiles={['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp']}
          encoding="terrarium"
          tileSize={512}
          maxzoom={16}
          attribution="© Mapterhorn"
        >
          <Layer
            id="hillshade"
            type="hillshade"
            layout={{ visibility: terrain ? 'visible' : 'none' }}
            paint={{
              'hillshade-shadow-color': appearance.chrome.textMuted,
              'hillshade-highlight-color': appearance.chrome.surface,
              'hillshade-exaggeration': 0.3,
            }}
          />
        </Source>
        {style?.sources.openmaptiles && camera.pitch > 0 && (
          <Layer
            id="context-buildings"
            source="openmaptiles"
            source-layer="building"
            type="fill-extrusion"
            minzoom={13}
            filter={['all', ['has', 'render_height'], ['>', ['get', 'render_height'], 0]]}
            paint={{
              'fill-extrusion-height': ['get', 'render_height'],
              'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
              'fill-extrusion-color': appearance.chrome.border,
              'fill-extrusion-opacity': 0.65,
            }}
          />
        )}
        <Source id="source-displacements" type="geojson" data={links}>
          <Layer
            id="displacements"
            type="line"
            paint={{
              'line-color': appearance.chrome.textMuted,
              'line-dasharray': [2, 2],
              'line-width': 1,
            }}
          />
        </Source>
        <Source
          id="dem"
          type="raster-dem"
          tiles={['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp']}
          encoding="terrarium"
          tileSize={512}
          maxzoom={16}
          attribution="© Mapterhorn"
        />
        <Source id="locations" type="geojson" data={points}>
          <Layer
            id="locations-circle"
            type="circle"
            paint={{
              'circle-radius': 7,
              'circle-color': [
                'case',
                ['==', ['get', 'kind'], 'source'],
                appearance.data.categorical[1],
                appearance.chrome.accent,
              ],
              'circle-stroke-width': 2,
              'circle-stroke-color': appearance.chrome.surface,
            }}
          />
        </Source>
        {outline && (
          <Source
            id="area"
            type="geojson"
            data={{ type: 'Feature', geometry: outline, properties: {} }}
          >
            <Layer
              id="area-fill"
              type="fill"
              paint={{ 'fill-color': appearance.chrome.accent, 'fill-opacity': 0.12 }}
            />
            <Layer
              id="area-line"
              type="line"
              paint={{ 'line-color': appearance.chrome.accent, 'line-width': 2 }}
            />
          </Source>
        )}
        <Source
          id="vertices"
          type="geojson"
          data={{
            type: 'FeatureCollection',
            features: vertices.map((p) => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: p },
              properties: {},
            })),
          }}
        >
          <Layer
            id="vertex-points"
            type="circle"
            paint={{ 'circle-radius': 5, 'circle-color': appearance.chrome.accent }}
          />
        </Source>
      </MapViewGL>
      <div className="map-caption">
        <span className="dot" /> Requested location <span className="dot source" /> Known source
        location <span className="spacer" /> Terrain is context, not weather resolution.
      </div>
      {error && (
        <p className="map-warning" role="status">
          {error}
        </p>
      )}
    </div>
  )
}

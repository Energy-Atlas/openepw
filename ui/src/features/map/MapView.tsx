import {
  Layer,
  Map as MapViewGL,
  Marker,
  NavigationControl,
  Source,
  type MapRef,
} from '@vis.gl/react-maplibre'
import type { GeoJSONSourceSpecification, StyleSpecification } from 'maplibre-gl'
import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Artifact, Schemas } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import type { Appearance } from '../../shell/appearances'
import { CoverageControl, type CoverageSetting } from './CoverageControl'
import { GeometryToolbar } from './GeometryToolbar'
import { PointGlyph, type DatasetPointStatus } from './PointGlyph'
import { geometry, type DrawMode, type Position } from './selection'

class MapBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false }
  static getDerivedStateFromError() { return { error: true } }
  render() {
    return this.state.error ? <div className="empty">3D map unavailable. Explore controls remain available in the stage panel.</div> : this.props.children
  }
}

export function MapView({ appearance }: { appearance: Appearance }) {
  return <MapBoundary><WeatherMap appearance={appearance} /></MapBoundary>
}

function WeatherMap({ appearance }: { appearance: Appearance }) {
  const ref = useRef<MapRef>(null)
  const host = useRef<HTMLDivElement>(null)
  const coverageRequested = useRef(false)
  const state = useApp()
  const [style, setStyle] = useState<StyleSpecification | null>(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState<DrawMode>('point')
  const [drawing, setDrawing] = useState(false)
  const [vertices, setVertices] = useState<Position[]>([])
  const [loaded, setLoaded] = useState(false)
  const [coverage, setCoverage] = useState<CoverageSetting[]>(() =>
    state.selectedCoverageIds.map((id) => ({ id, opacity: 0.32 })),
  )
  const [camera, setCamera] = useState({ longitude: -76.5, latitude: 42.44, zoom: 4, pitch: 48, bearing: 0 })

  useEffect(() => {
    const controller = new AbortController()
    fetch('https://tiles.openfreemap.org/styles/positron', { signal: controller.signal })
      .then((response) => { if (!response.ok) throw Error(); return response.json() })
      .then(setStyle)
      .catch((reason) => { if (reason.name !== 'AbortError') setError('Basemap unavailable. Location selection remains usable.') })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (!state.coverageLayers.length && !state.busy && !coverageRequested.current) {
      coverageRequested.current = true
      run({ type: 'loadCoverage' })
    }
  }, [state.coverageLayers.length, state.busy])
  useEffect(() => {
    if (!host.current) return
    const resize = new ResizeObserver(() => ref.current?.resize())
    resize.observe(host.current)
    return () => resize.disconnect()
  }, [])
  useEffect(() => {
    if (!loaded) return
    const map = ref.current?.getMap()
    map?.setProjection({ type: 'globe' })
    map?.setTerrain({ source: 'dem', exaggeration: 1 })
  }, [loaded, style])

  const themed = useMemo<StyleSpecification>(() => {
    if (!style) return { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': appearance.chrome.bg } }] }
    const next = structuredClone(style)
    next.layers = next.layers.map((layer) => {
      if (layer.type === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': appearance.chrome.bg } }
      if (layer.type === 'fill') return { ...layer, paint: { ...layer.paint, 'fill-color': layer.id.includes('water') ? appearance.chrome.surfaceRaised : appearance.chrome.surface } }
      if (layer.type === 'line') return { ...layer, paint: { ...layer.paint, 'line-color': appearance.chrome.border } }
      if (layer.type === 'symbol') return { ...layer, paint: { ...layer.paint, 'text-color': appearance.chrome.textMuted, 'text-halo-color': appearance.chrome.bg } }
      return layer
    })
    return next
  }, [style, appearance])

  const locations = state.spatialPreview?.locations ?? []
  const sourceLocations = (state.discovery?.candidates ?? []).map((candidate) => candidate.source.location).filter((location): location is Schemas['Location'] => !!location)
  const links = { type: 'FeatureCollection' as const, features: locations.length === 1 ? sourceLocations.map((point) => ({ type: 'Feature' as const, geometry: { type: 'LineString' as const, coordinates: [[locations[0].lon, locations[0].lat], [point.lon, point.lat]] }, properties: {} })) : [] }
  const outline = draftOutline(state.draft.locations)
  const activeCoverage = coverage.flatMap((setting) => {
    const layer = state.coverageLayers.find((item) => item.id === setting.id)
    return layer ? [{ layer, ...setting }] : []
  })

  function apply(points: Position[]) {
    try {
      run({ type: 'editQuery', patch: { locations: geometry(mode, points) } })
      setDrawing(false)
      setVertices([])
      setError('')
      queueMicrotask(() => run({ type: 'previewSpatial' }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }
  function fitSelection() {
    if (locations.length === 1) ref.current?.flyTo({ center: [locations[0].lon, locations[0].lat], zoom: 8, pitch: 48 })
    else if (locations.length > 1) ref.current?.fitBounds([[Math.min(...locations.map((point) => point.lon)), Math.min(...locations.map((point) => point.lat))], [Math.max(...locations.map((point) => point.lon)), Math.max(...locations.map((point) => point.lat))]], { padding: 60 })
  }
  function changeCoverage(next: CoverageSetting[]) {
    setCoverage(next)
    run({ type: 'setCoverageSelection', ids: next.map((item) => item.id) })
  }

  return <div className="map-page" ref={host}>
    {state.stage === 'explore' && <GeometryToolbar mode={mode} drawing={drawing} vertices={vertices} onMode={setMode} onDrawing={setDrawing} onVertices={setVertices} onFinish={() => apply(vertices)} onClear={() => { setVertices([]); run({ type: 'editQuery', patch: { locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 } } }); queueMicrotask(() => run({ type: 'previewSpatial' })) }} />}
    <CoverageControl layers={state.coverageLayers} selected={coverage} onChange={changeCoverage} />
    <button type="button" className="fit-selection" disabled={!locations.length} onClick={fitSelection}>Fit selection</button>
    {drawing && <div className="map-instruction">Click the globe to add {mode === 'bbox' ? 'two corners' : mode === 'point' ? 'a point' : 'vertices'}. Arrow keys nudge the latest vertex; Shift moves farther.</div>}
    <MapViewGL ref={ref} {...camera} onMove={(event) => setCamera(event.viewState)} mapStyle={themed} onLoad={() => setLoaded(true)} onError={() => setError('Some map tiles could not load. Weather requests are independent of map tiles.')} onClick={(event) => {
      if (!drawing) return
      const next = [...vertices, [event.lngLat.lng, event.lngLat.lat] as Position]
      setVertices(next)
      if (mode === 'point' || (mode === 'bbox' && next.length === 2)) apply(next)
    }}>
      <NavigationControl visualizePitch />
      <Source id="dem" type="raster-dem" tiles={['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp']} encoding="terrarium" tileSize={512} maxzoom={16} attribution="© Mapterhorn" />
      <Source id="hillshade-dem" type="raster-dem" tiles={['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp']} encoding="terrarium" tileSize={512} maxzoom={16} attribution="© Mapterhorn">
        <Layer id="hillshade" type="hillshade" paint={{ 'hillshade-shadow-color': appearance.chrome.textMuted, 'hillshade-highlight-color': appearance.chrome.surface, 'hillshade-exaggeration': 0.3 }} />
      </Source>
      {activeCoverage.map(({ layer, opacity }) => layer.kind === 'vector' && layer.geometry ? <Source key={layer.id} id={`coverage-${layer.id}`} type="geojson" data={layer.geometry as GeoJSONSourceSpecification['data']}><Layer id={`coverage-fill-${layer.id}`} type="fill" paint={{ 'fill-color': appearance.data.categorical[2], 'fill-opacity': opacity }} /><Layer id={`coverage-line-${layer.id}`} type="line" paint={{ 'line-color': appearance.data.categorical[2], 'line-width': 1.5 }} /></Source> : layer.kind === 'raster' && layer.tiles ? <Source key={layer.id} id={`coverage-${layer.id}`} type="raster" tiles={[layer.tiles]}><Layer id={`coverage-raster-${layer.id}`} type="raster" paint={{ 'raster-opacity': opacity }} /></Source> : null)}
      <Source id="source-displacements" type="geojson" data={links}><Layer id="displacements" type="line" paint={{ 'line-color': appearance.chrome.textMuted, 'line-dasharray': [2, 2], 'line-width': 1 }} /></Source>
      {outline && <Source id="area" type="geojson" data={{ type: 'Feature', geometry: outline, properties: {} }}><Layer id="area-fill" type="fill" paint={{ 'fill-color': appearance.chrome.accent, 'fill-opacity': 0.12 }} /><Layer id="area-line" type="line" paint={{ 'line-color': appearance.chrome.accent, 'line-width': 2 }} /></Source>}
      <Source id="vertices" type="geojson" data={{ type: 'FeatureCollection', features: vertices.map((point) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: point }, properties: {} })) }}><Layer id="vertex-points" type="circle" paint={{ 'circle-radius': 5, 'circle-color': appearance.chrome.accent }} /></Source>
      {locations.map((location, index) => <Marker key={location.id ?? `${location.lon}-${location.lat}`} longitude={location.lon} latitude={location.lat} anchor="center"><PointGlyph label={location.name || `Sample ${index + 1}`} statuses={pointStatuses(state, location, appearance)} artifacts={pointArtifacts(state, location)} /></Marker>)}
    </MapViewGL>
    <div className="map-caption"><span className="dot" /> Authoritative sampled point <span className="spacer" /> Terrain is context, not weather resolution.</div>
    {state.spatialPreview?.truncated && <p className="map-limit" role="status">Showing {state.spatialPreview.returned_count.toLocaleString()} of {state.spatialPreview.total_count.toLocaleString()} authoritative samples.</p>}
    {state.spatialPreview && !state.spatialPreview.executable && <p className="map-limit blocking" role="alert">Execution limit {state.spatialPreview.execution_limit.toLocaleString()} exceeded by {state.spatialPreview.planned_output_count.toLocaleString()} planned outputs.</p>}
    {error && <p className="map-warning" role="status">{error}</p>}
  </div>
}

function draftOutline(locations: Schemas['WeatherRequest-Input']['locations']) {
  if (!Array.isArray(locations) && 'coordinates' in locations) return locations
  if (!Array.isArray(locations) && 'west' in locations) return { type: 'Polygon' as const, coordinates: [[[locations.west, locations.south], [locations.east, locations.south], [locations.east, locations.north], [locations.west, locations.north], [locations.west, locations.south]]] }
  return null
}

function pointStatuses(state: ReturnType<typeof useApp.getState>, location: Schemas['Location'], appearance: Appearance): DatasetPointStatus[] {
  const colors = appearance.data.categorical
  return state.selectedDatasets.map((selection, index) => {
    const candidate = state.discovery?.candidates.find((item) => item.source.provider === selection.provider && item.source.dataset === selection.dataset && (!item.location_id || item.location_id === location.id))
    const artifact = pointArtifacts(state, location).some((item) => item.media_type === 'application/vnd.energyplus.epw')
    const failed = state.downloadJobs.some((job) => ['failed', 'partially_completed'].includes(job.state)) && !artifact
    const status: DatasetPointStatus['state'] = artifact ? 'complete' : failed ? 'failed' : candidate?.requires_credentials?.length ? 'gated' : candidate ? 'selected' : 'unavailable'
    return { label: `${selection.provider} · ${selection.dataset}`, state: status, color: colors[index % colors.length] }
  })
}

function pointArtifacts(state: ReturnType<typeof useApp.getState>, location: Schemas['Location']): Artifact[] {
  const names = new Set((state.weatherPlan?.outputs ?? []).filter((output) => !location.id || output.requested_location_id === location.id).map((output) => output.name))
  const artifacts = state.downloadJobs.flatMap((job) => job.bundle?.weather ?? [])
  return artifacts.filter((artifact) => names.size === 0 || [...names].some((name) => artifact.path.endsWith(name)))
}

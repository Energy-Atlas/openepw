import { useEffect, useRef, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { appearanceStyle, applyAppearance, applyScene, scenePitch, type Appearance, type SceneSettings } from './scene'
import { renderShadows } from './renderShadows'
import type { WeatherGeography } from '../geography'
import type { AvailabilitySummary } from '../types'

const initial: SceneSettings = {
  appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1,
  dayOfYear: 172, utcMinutes: 960, lightIntensity: 100, diffusion: 25,
  haze: 20, shadows: true,
}

const appearances: Array<[Appearance, string]> = [
  ['light', 'Light'], ['dark', 'Dark'], ['monochrome', 'Technical monochrome'],
  ['landform', 'Landform'], ['clean', 'Clean technical'], ['engineering', 'Dark engineering'],
]

type MapPoint = { id?: string; name?: string; lat: number; lon: number }

export function MapCanvas({ location, candidates = [], geography, resolvedPoints = [], availability, onPickPoint, onPickCandidate, onPickGeometry }: {
  location?: MapPoint | null
  candidates?: MapPoint[]
  geography?: WeatherGeography | null
  resolvedPoints?: MapPoint[]
  availability?: AvailabilitySummary | null
  onPickPoint?: (point: MapPoint) => void
  onPickCandidate?: (id: string) => void
  onPickGeometry?: (geography: WeatherGeography) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const settingsRef = useRef(initial)
  const awaitingStyleIdle = useRef(false)
  const [settings, setSettings] = useState(initial)
  const [status, setStatus] = useState('Loading map')
  const [styleEpoch, setStyleEpoch] = useState(0)
  const [shadowStatus, setShadowStatus] = useState('Shadows paused in flat view.')
  const shadowTimer = useRef<number | null>(null)
  const scheduleShadowsRef = useRef<() => void>(() => {})
  const [picking, setPicking] = useState(false)
  const [drawMode, setDrawMode] = useState<'polygon' | 'box' | null>(null)
  const [showEvidence, setShowEvidence] = useState(false)
  const [vertices, setVertices] = useState<Array<[number, number]>>([])
  const drawRef = useRef<'polygon' | 'box' | null>(null)
  const verticesRef = useRef<Array<[number, number]>>([])
  const pickGeometryRef = useRef(onPickGeometry)
  const candidateRef = useRef(candidates)
  const pickPointRef = useRef(onPickPoint)
  const pickCandidateRef = useRef(onPickCandidate)

  useEffect(() => { candidateRef.current = candidates; pickPointRef.current = onPickPoint;
    pickCandidateRef.current = onPickCandidate; pickGeometryRef.current = onPickGeometry },
  [candidates, onPickPoint, onPickCandidate, onPickGeometry])

  function endDraw() { drawRef.current = null; verticesRef.current = []; setDrawMode(null); setVertices([]) }
  function beginDraw(mode: 'polygon' | 'box') {
    drawRef.current = mode; verticesRef.current = []; setDrawMode(mode); setVertices([])
    setPicking(false)
    if (map.current) map.current.getCanvas().dataset.picking = 'false'
  }

  function change(patch: Partial<SceneSettings>) {
    setSettings(current => ({ ...current, ...patch }))
  }

  useEffect(() => {
    if (!host.current) return
    if (!window.WebGLRenderingContext) {
      setStatus('Interactive map requires WebGL. Use chat to enter coordinates or a place.')
      return
    }
    let cancelled = false
    let instance: MapLibreMap | null = null
    function scheduleShadows() {
      if (shadowTimer.current !== null) window.clearTimeout(shadowTimer.current)
      shadowTimer.current = window.setTimeout(() => {
        if (!instance || cancelled) return
        try { setShadowStatus(renderShadows(instance, settingsRef.current)) }
        catch { setShadowStatus('Cast shadow renderer unavailable; map and weather chat remain usable.') }
      }, 250)
    }
    scheduleShadowsRef.current = scheduleShadows
    void import('maplibre-gl').then(maplibregl => {
      if (cancelled || !host.current) return
      maplibregl.setWorkerUrl(workerUrl)
      const sceneMap = new maplibregl.Map({
        container: host.current,
        style: appearanceStyle(settingsRef.current.appearance),
        center: [0, 18], zoom: 1.65,
        canvasContextAttributes: { antialias: true },
      })
      instance = sceneMap
      map.current = sceneMap
      sceneMap.on('style.load', () => {
        try {
          applyAppearance(sceneMap, settingsRef.current.appearance)
          applyScene(sceneMap, { ...settingsRef.current, terrain: false })
          sceneMap.jumpTo({ pitch: scenePitch(settingsRef.current) })
          setStyleEpoch(value => value + 1)
          setStatus('Map ready')
          scheduleShadows()
          sceneMap.once('idle', () => {
            if (cancelled || !awaitingStyleIdle.current) return
            awaitingStyleIdle.current = false
            try { applyScene(sceneMap, settingsRef.current); scheduleShadows() }
            catch { setStatus('Terrain unavailable; map and chat remain usable.') }
          })
        }
        catch { setStatus('Map scene unavailable; chat and coordinates remain usable.') }
      })
      sceneMap.on('error', () => setStatus('Some map tiles could not load. Chat remains available.'))
      sceneMap.on('moveend', () => {
        setStatus(`Map ready · zoom ${sceneMap.getZoom().toFixed(1)}`)
        scheduleShadows()
      })
      sceneMap.on('sourcedata', event => {
        if (event.sourceId === 'openmaptiles' || event.sourceId === 'openepw-terrain') scheduleShadows()
      })
      sceneMap.on('click', event => {
        if (drawRef.current) {
          const point: [number, number] = [((event.lngLat.lng + 180) % 360 + 360) % 360 - 180,
            event.lngLat.lat]
          const next = [...verticesRef.current, point]
          verticesRef.current = next; setVertices(next)
          if (drawRef.current === 'box' && next.length === 2) {
            pickGeometryRef.current?.({ west: next[0][0], south: Math.min(next[0][1], next[1][1]),
              east: next[1][0], north: Math.max(next[0][1], next[1][1]) })
            endDraw()
          }
          return
        }
        const hit = sceneMap.getLayer('openepw-candidates')
          ? sceneMap.queryRenderedFeatures(event.point, { layers: ['openepw-candidates'] }) : []
        if (hit.length && typeof hit[0].properties?.id === 'string') {
          pickCandidateRef.current?.(hit[0].properties.id)
          return
        }
        if (sceneMap.getCanvas().dataset.picking === 'true') {
          pickPointRef.current?.({ lat: event.lngLat.lat,
            lon: ((event.lngLat.lng + 180) % 360 + 360) % 360 - 180 })
          sceneMap.getCanvas().dataset.picking = 'false'
          setPicking(false)
        }
      })
      sceneMap.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-left')
    }).catch(() => setStatus('Map unavailable. Use chat to enter coordinates or a place.'))
    return () => { cancelled = true; if (shadowTimer.current !== null) window.clearTimeout(shadowTimer.current);
      instance?.remove(); map.current = null }
  }, [])

  useEffect(() => {
    settingsRef.current = settings
    if (!map.current) return
    try { if (map.current.isStyleLoaded()) applyAppearance(map.current, settings.appearance);
      applyScene(map.current, awaitingStyleIdle.current ? { ...settings, terrain: false } : settings) }
    catch { setStatus('Map scene unavailable; chat and coordinates remain usable.') }
    scheduleShadowsRef.current()
  }, [settings])

  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap || !location) return
    sceneMap.easeTo({ center: [location.lon, location.lat], zoom: Math.max(sceneMap.getZoom(), 11),
      padding: { right: window.innerWidth > 650 ? 410 : 0 }, duration: 900 })
  }, [location?.lat, location?.lon, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap?.isStyleLoaded()) return
    const features = [
      ...candidates.map(point => ({ type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [point.lon, point.lat] },
        properties: { id: point.id ?? '', name: point.name ?? '', selected: false } })),
      ...(location ? [{ type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [location.lon, location.lat] },
        properties: { id: location.id ?? '', name: location.name ?? '', selected: true } }] : []),
    ]
    if (!sceneMap.getSource('openepw-candidates')) {
      sceneMap.addSource('openepw-candidates', { type: 'geojson', data: { type: 'FeatureCollection', features } })
      sceneMap.addLayer({ id: 'openepw-candidates', type: 'circle', source: 'openepw-candidates',
        paint: { 'circle-radius': 7, 'circle-color': ['case', ['get', 'selected'], '#d69b36', '#237e8b'],
          'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' } })
    } else {
      (sceneMap.getSource('openepw-candidates') as import('maplibre-gl').GeoJSONSource).setData({
        type: 'FeatureCollection', features,
      })
    }
  }, [candidates, location, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap?.isStyleLoaded()) return
    const data = { type: 'FeatureCollection' as const, features: vertices.length ? [{
      type: 'Feature' as const, properties: {}, geometry: {
        type: 'LineString' as const, coordinates: vertices,
      },
    }] : [] }
    if (!sceneMap.getSource('openepw-drawing')) {
      sceneMap.addSource('openepw-drawing', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-drawing', type: 'line', source: 'openepw-drawing',
        paint: { 'line-color': '#d69b36', 'line-width': 3 } })
    } else {
      (sceneMap.getSource('openepw-drawing') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [vertices, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap?.isStyleLoaded()) return
    const features: Array<GeoJSON.Feature> = []
    if (geography && !Array.isArray(geography) && 'type' in geography && geography.type === 'Polygon') {
      features.push({ type: 'Feature', properties: {}, geometry: geography })
    } else if (geography && !Array.isArray(geography) && 'west' in geography) {
      const boxes = geography.west <= geography.east ? [[geography.west, geography.east]]
        : [[geography.west, 180], [-180, geography.east]]
      for (const [west, east] of boxes) {
        features.push({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
          [west, geography.south], [east, geography.south], [east, geography.north],
          [west, geography.north], [west, geography.south],
        ]] } })
      }
    }
    for (const point of resolvedPoints) {
      features.push({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [point.lon, point.lat] } })
    }
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    if (!sceneMap.getSource('openepw-selection')) {
      sceneMap.addSource('openepw-selection', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-selection-fill', type: 'fill', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#237e8b', 'fill-opacity': .14 } })
      sceneMap.addLayer({ id: 'openepw-selection-outline', type: 'line', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'line-color': '#237e8b', 'line-width': 2 } })
      sceneMap.addLayer({ id: 'openepw-selection-points', type: 'circle', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#237e8b',
          'circle-stroke-width': 1, 'circle-stroke-color': '#ffffff' } })
    } else {
      (sceneMap.getSource('openepw-selection') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [geography, resolvedPoints, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap?.isStyleLoaded()) return
    const seen = new Set<string>()
    const features: GeoJSON.Feature[] = []
    if (showEvidence) for (const option of availability?.options ?? []) {
      const footprint = option.footprint
      if (!footprint) continue
      const key = `${option.provider}:${footprint.join(',')}`
      if (seen.has(key) || features.length >= 12) continue
      seen.add(key)
      const [west, south, east, north] = footprint
      if (west >= east || south >= north) continue
      features.push({ type: 'Feature', properties: { provider: option.provider,
        status: option.status }, geometry: { type: 'Polygon', coordinates: [[
        [west, south], [east, south], [east, north], [west, north], [west, south],
      ]] } })
    }
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    if (!sceneMap.getSource('openepw-evidence')) {
      sceneMap.addSource('openepw-evidence', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-evidence', type: 'line', source: 'openepw-evidence',
        paint: { 'line-color': '#647782', 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': .75 } })
    } else {
      (sceneMap.getSource('openepw-evidence') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [availability, showEvidence, styleEpoch])

  function setAppearance(appearance: Appearance) {
    awaitingStyleIdle.current = Boolean(settingsRef.current.terrain)
    if (awaitingStyleIdle.current) map.current?.setTerrain(null)
    change({ appearance })
    map.current?.setStyle(appearanceStyle(appearance))
  }

  return <div className="map-canvas" aria-label="Weather map">
    <div ref={host} className="map-engine" aria-hidden="true" />
    <div className="map-brand">OpenEPW <span>Weather across places and years</span></div>
    <section className="scene-controls" aria-label="Map scene controls">
      {status.includes('unavailable') || status.includes('could not load') ?
        <button type="button" onClick={() => map.current?.setStyle(appearanceStyle(settings.appearance))}>Retry map</button> : null}
      <button type="button" aria-pressed={picking} onClick={() => {
        setPicking(value => { const next = !value; if (map.current) map.current.getCanvas().dataset.picking = String(next); return next })
      }}>Choose point</button>
      <button type="button" aria-pressed={drawMode === 'box'} onClick={() => beginDraw('box')}>
        Draw box</button>
      <button type="button" aria-pressed={drawMode === 'polygon'} onClick={() => beginDraw('polygon')}>
        Draw polygon</button>
      {availability && <label><input type="checkbox" checked={showEvidence}
        onChange={event => setShowEvidence(event.target.checked)} /> Source scope outlines</label>}
      {showEvidence && <p>Dashed outlines are documented source scope, not verified point availability.
        Selected-point assessment and evidence dates are in the plan review.</p>}
      {drawMode && <div className="draw-actions"><span>{drawMode === 'box' ? 'Choose opposite corners' : `${vertices.length} vertices`}</span>
        {drawMode === 'polygon' && <button type="button" disabled={vertices.length < 3} onClick={() => {
          const ring = [...vertices, vertices[0]]
          pickGeometryRef.current?.({ type: 'Polygon', coordinates: [ring] })
          endDraw()
        }}>Finish polygon</button>}
        <button type="button" onClick={endDraw}>Cancel drawing</button></div>}
      <button type="button" disabled={!location} onClick={() => {
        change({ view3d: true })
        map.current?.easeTo({ center: [location!.lon, location!.lat], zoom: 15.5, pitch: 50,
          padding: { right: window.innerWidth > 650 ? 410 : 0 }, duration: 700 })
      }}>District view</button>
      <button type="button" aria-pressed={settings.view3d} onClick={() => {
        const view3d = !settings.view3d
        change({ view3d })
        map.current?.easeTo({ pitch: view3d ? 50 : 0, duration: 400 })
      }}>3D view</button>
      <label><input type="checkbox" checked={settings.terrain} disabled={!settings.view3d}
        onChange={event => change({ terrain: event.target.checked })} /> Terrain</label>
      <label>Appearance <select value={settings.appearance} onChange={event => setAppearance(event.target.value as Appearance)}>
        {appearances.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
      </select></label>
      {settings.view3d && <details><summary>Sun and relief</summary>
        <label>Terrain scale <input type="range" min="1" max="10" value={settings.terrainExaggeration}
          disabled={!settings.terrain} onChange={event => change({ terrainExaggeration: Number(event.target.value) })} /> {settings.terrainExaggeration}×</label>
        <label>Day of year <input type="number" min="1" max="365" value={settings.dayOfYear}
          onChange={event => change({ dayOfYear: Number(event.target.value) })} /></label>
        <label>UTC time <input type="time" value={`${String(Math.floor(settings.utcMinutes / 60)).padStart(2, '0')}:${String(settings.utcMinutes % 60).padStart(2, '0')}`}
          onChange={event => { const [hours, minutes] = event.target.value.split(':').map(Number); change({ utcMinutes: hours * 60 + minutes }) }} /></label>
        <div className="time-presets"><button type="button" onClick={() => change({ utcMinutes: 720 })}>12:00 UTC</button>
          <button type="button" onClick={() => change({ utcMinutes: 960 })}>16:00 UTC</button>
          <button type="button" onClick={() => change({ utcMinutes: 1260 })}>21:00 UTC</button>
          <button type="button" onClick={() => change({ utcMinutes: 120 })}>02:00 UTC</button></div>
        <label>Light <input type="range" min="0" max="150" value={settings.lightIntensity}
          onChange={event => change({ lightIntensity: Number(event.target.value) })} /> {settings.lightIntensity}%</label>
        <label>Diffusion <input type="range" min="0" max="100" value={settings.diffusion}
          onChange={event => change({ diffusion: Number(event.target.value) })} /> {settings.diffusion}%</label>
        <label>Haze <input type="range" min="0" max="100" value={settings.haze}
          onChange={event => change({ haze: Number(event.target.value) })} /> {settings.haze}%</label>
        <label><input type="checkbox" checked={settings.shadows} onChange={event => change({ shadows: event.target.checked })} /> Cast shadows</label>
        <p>Scene lighting and buildings are decorative; they do not change weather data or simulations.</p>
      </details>}
    </section>
    <div className="map-status" role="status">{status}</div>
    {settings.view3d && <div className="shadow-status" role="status">{shadowStatus}</div>}
    <div className="scene-attribution">
      <a href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a> ·
      <a href="https://openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> ·
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
      {settings.terrain && <> · <a href="https://mapterhorn.com/attribution/" target="_blank" rel="noreferrer">Mapterhorn</a></>}
    </div>
  </div>
}

import { useEffect, useRef, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { appearanceStyle, applyAppearance, applyLighting, applyScene, autoView3d, scenePitch, type SceneSettings } from './scene'
import { renderShadows } from './renderShadows'
import { availabilityFeatures } from './evidence'
import { MAP_PALETTE, catalogFeatures, catalogLayerSpecs, layerSwatch, legendRows } from './catalogLayers'
import { utcSceneTime } from './sun'
import type { WeatherGeography } from '../geography'
import type { AvailabilitySummary, CatalogLayer, CatalogMap } from '../types'

const initial: SceneSettings = {
  appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1,
  ...utcSceneTime(new Date()), lightIntensity: 100, diffusion: 25,
  haze: 20, shadows: true,
}

type MapPoint = { id?: string; name?: string; lat: number; lon: number }

// isStyleLoaded() is also false while any tile is loading; overlays only need a parsed style.
function styleParsed(map: MapLibreMap | null): map is MapLibreMap {
  return Boolean(map?.getStyle())
}

export function MapCanvas({ location, candidates = [], geography, resolvedPoints = [], availability, catalogMap, years = [],
  pickMode = false, onExitPickMode, onPickPoint, onPickCandidate, onPickGeometry }: {
  location?: MapPoint | null
  candidates?: MapPoint[]
  geography?: WeatherGeography | null
  resolvedPoints?: MapPoint[]
  availability?: AvailabilitySummary | null
  catalogMap?: CatalogMap | null
  years?: number[]
  pickMode?: boolean
  onExitPickMode?: () => void
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
  const [hiddenLayers, setHiddenLayers] = useState<string[]>([])
  const [drawMode, setDrawMode] = useState<'polygon' | 'box' | null>(null)
  const [vertices, setVertices] = useState<Array<[number, number]>>([])
  const drawRef = useRef<'polygon' | 'box' | null>(null)
  const verticesRef = useRef<Array<[number, number]>>([])
  const pickGeometryRef = useRef(onPickGeometry)
  const candidateRef = useRef(candidates)
  const pickPointRef = useRef(onPickPoint)
  const pickCandidateRef = useRef(onPickCandidate)
  const exitPickRef = useRef(onExitPickMode)

  useEffect(() => { candidateRef.current = candidates; pickPointRef.current = onPickPoint;
    pickCandidateRef.current = onPickCandidate; pickGeometryRef.current = onPickGeometry;
    exitPickRef.current = onExitPickMode },
  [candidates, onPickPoint, onPickCandidate, onPickGeometry, onExitPickMode])

  useEffect(() => {
    if (!pickMode) endDraw()
    setPicking(pickMode)
    if (map.current) map.current.getCanvas().dataset.picking = String(pickMode)
  }, [pickMode])

  function endDraw() { drawRef.current = null; verticesRef.current = []; setDrawMode(null); setVertices([]) }
  function beginDraw(mode: 'polygon' | 'box') {
    drawRef.current = mode; verticesRef.current = []; setDrawMode(mode); setVertices([])
    setPicking(false)
    if (map.current) map.current.getCanvas().dataset.picking = 'false'
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
        // The floating chat covers the bottom-right corner; .scene-attribution carries the same credits.
        attributionControl: false,
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
        const view3d = autoView3d(sceneMap.getZoom(), settingsRef.current.view3d)
        if (view3d !== settingsRef.current.view3d) {
          settingsRef.current = { ...settingsRef.current, view3d }
          setSettings(settingsRef.current)
          sceneMap.easeTo({ pitch: scenePitch(settingsRef.current), duration: 500 })
        }
        if (styleParsed(sceneMap) && !awaitingStyleIdle.current) {
          try { applyLighting(sceneMap, settingsRef.current) }
          catch { setStatus('Scene lighting unavailable; map and chat remain usable.') }
        }
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
            exitPickRef.current?.()
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
          exitPickRef.current?.()
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
    try { if (styleParsed(map.current)) applyAppearance(map.current, settings.appearance);
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
    if (!styleParsed(sceneMap)) return
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
        paint: { 'circle-radius': ['case', ['get', 'selected'], 7, 6],
          'circle-color': MAP_PALETTE.HERO, 'circle-opacity': ['case', ['get', 'selected'], 1, 0],
          'circle-stroke-width': 2,
          'circle-stroke-color': MAP_PALETTE.CANDIDATE } })
    } else {
      (sceneMap.getSource('openepw-candidates') as import('maplibre-gl').GeoJSONSource).setData({
        type: 'FeatureCollection', features,
      })
    }
  }, [candidates, location, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap)) return
    const data = { type: 'FeatureCollection' as const, features: vertices.length ? [{
      type: 'Feature' as const, properties: {}, geometry: {
        type: 'LineString' as const, coordinates: vertices,
      },
    }] : [] }
    if (!sceneMap.getSource('openepw-drawing')) {
      sceneMap.addSource('openepw-drawing', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-drawing', type: 'line', source: 'openepw-drawing',
        paint: { 'line-color': MAP_PALETTE.HERO_LINE, 'line-width': 3 } })
    } else {
      (sceneMap.getSource('openepw-drawing') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [vertices, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap)) return
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
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': MAP_PALETTE.HERO, 'fill-opacity': .14 } })
      sceneMap.addLayer({ id: 'openepw-selection-outline', type: 'line', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'line-color': MAP_PALETTE.HERO_LINE, 'line-width': 2 } })
      sceneMap.addLayer({ id: 'openepw-selection-points', type: 'circle', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': MAP_PALETTE.HERO,
          'circle-stroke-width': 1, 'circle-stroke-color': MAP_PALETTE.CANDIDATE } })
    } else {
      (sceneMap.getSource('openepw-selection') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [geography, resolvedPoints, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap)) return
    const data = availabilityFeatures(availability)
    if (!sceneMap.getSource('openepw-evidence')) {
      sceneMap.addSource('openepw-evidence', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-evidence-fill', type: 'fill', source: 'openepw-evidence',
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': .045 } })
      sceneMap.addLayer({ id: 'openepw-evidence-line', type: 'line', source: 'openepw-evidence',
        paint: { 'line-color': ['get', 'color'], 'line-width': 1.1,
          'line-dasharray': [2, 2], 'line-opacity': .34 } })
    } else {
      (sceneMap.getSource('openepw-evidence') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [availability, styleEpoch])

  const yearKey = years.join(',')
  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap) || !catalogMap) return
    // Catalog context sits under the user's selection, candidates and drawing; broad extents lowest.
    const own = new Set(['openepw-selection-fill', 'openepw-drawing', 'openepw-candidates', 'openepw-evidence-fill'])
    const before = sceneMap.getStyle().layers.find(item => own.has(item.id))?.id
    const stack = ['extent', 'cells', 'area', 'sites', 'stations']
    const ordered = [...catalogMap.layers].sort((a, b) => stack.indexOf(a.kind) - stack.indexOf(b.kind))
    for (const layer of ordered) {
      const id = `openepw-catalog-${layer.id}`
      const data = catalogFeatures(layer, layer.kind === 'stations' ? years : [])
      const source = sceneMap.getSource(id) as import('maplibre-gl').GeoJSONSource | undefined
      if (source) source.setData(data)
      else {
        sceneMap.addSource(id, { type: 'geojson', data })
        for (const spec of catalogLayerSpecs(layer, id)) sceneMap.addLayer(spec, before)
      }
      const visibility = hiddenLayers.includes(layer.id) ? 'none' : 'visible'
      for (const suffix of ['fill', 'line', 'point'])
        if (sceneMap.getLayer(`${id}-${suffix}`)) sceneMap.setLayoutProperty(`${id}-${suffix}`, 'visibility', visibility)
    }
  }, [catalogMap, yearKey, hiddenLayers, styleEpoch])

  return <div className="map-canvas" aria-label="Weather map">
    <div ref={host} className="map-engine" aria-hidden="true" />
    {pickMode && <section className="pick-toolbar" role="toolbar" aria-label="Pick geography">
      <strong>Pick geography</strong>
      <button type="button" aria-pressed={picking && !drawMode} onClick={() => {
        endDraw(); setPicking(true)
        if (map.current) map.current.getCanvas().dataset.picking = 'true'
      }}>Choose point</button>
      <button type="button" aria-pressed={drawMode === 'box'} onClick={() => beginDraw('box')}>Draw box</button>
      <button type="button" aria-pressed={drawMode === 'polygon'} onClick={() => beginDraw('polygon')}>Draw polygon</button>
      {drawMode && <div className="draw-actions"><span>{drawMode === 'box' ? 'Choose opposite corners' : `${vertices.length} vertices`}</span>
        {drawMode === 'polygon' && <button type="button" disabled={vertices.length < 3} onClick={() => {
          const ring = [...vertices, vertices[0]]
          pickGeometryRef.current?.({ type: 'Polygon', coordinates: [ring] })
          endDraw()
          onExitPickMode?.()
        }}>Finish polygon</button>}
        <button type="button" onClick={() => { endDraw(); setPicking(true);
          if (map.current) map.current.getCanvas().dataset.picking = 'true' }}>Reset drawing</button></div>}
      <button type="button" onClick={onExitPickMode}>Close map input</button>
    </section>}
    {catalogMap && <aside className="evidence-legend" aria-label="Data availability scope">
      <strong>Where Stage 1 found weather sources</strong>
      <small className="legend-key">dot = record · ring = approximate or candidate · shade = source grid ·
        dashed = documented extent · amber = your selection</small>
      {legendRows(catalogMap.layers).map(row => <label key={row.ids.join()} className="scope-row" title={row.layers
        .map(layer => layer.caveat).join(' ')}>
        <input type="checkbox" checked={!row.ids.every(id => hiddenLayers.includes(id))} onChange={() =>
          setHiddenLayers(current => row.ids.every(id => current.includes(id))
            ? current.filter(item => !row.ids.includes(item)) : [...new Set([...current, ...row.ids])])} />
        <i className={`swatch swatch-${layerSwatch(row.kind).shape}`} style={{ color: layerSwatch(row.kind).color }} />
        <span>{row.label}</span>
        <small>{layerCount(row.layers[0], years)}</small>
      </label>)}
      <details><summary>What these layers mean</summary>
        {catalogMap.layers.map(layer => <p key={layer.id}><b>{layer.label}.</b> {layer.caveat}
          {layer.evidence_dates.length ? ` Evidence ${layer.evidence_dates.at(-1)}.` : ''}</p>)}
        {catalogMap.unmapped.length > 0 && <p>No reviewed geometry: {catalogMap.unmapped
          .map(item => `${item.provider}/${item.dataset}`).join(', ')}.</p>}
        <p>Credits: NOAA NCEI ISD; OneBuilding.org; NLR NSRDB (CC BY 3.0 US); PVGIS © European Union/JRC;
          Copernicus ERA5 and Open-Meteo.</p>
      </details>
      <small className="legend-source">Stage 1 catalog · {catalogMap.snapshot?.created_at.slice(0, 10) ?? 'bundled contracts'}
        {' '}· documentary, not point eligibility</small>
    </aside>}
    <div className="map-status" role="status">{status}
      {status.includes('unavailable') || status.includes('could not load') ?
        <button type="button" onClick={() => map.current?.setStyle(appearanceStyle(settings.appearance))}>Retry map</button> : null}
    </div>
    {settings.view3d && <div className="shadow-status" role="status">{shadowStatus}</div>}
    <div className="scene-attribution">
      <a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a> ·
      <a href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a> ·
      <a href="https://openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> ·
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
      {settings.terrain && <> · <a href="https://mapterhorn.com/attribution/" target="_blank" rel="noreferrer">Mapterhorn</a></>}
    </div>
  </div>
}

function layerCount(layer: CatalogLayer, years: number[]): string {
  if (layer.kind === 'stations') return years.length
    ? `${catalogFeatures(layer, years).features.length.toLocaleString()} reporting ${years.length === 1 ? years[0] : `${years[0]}–${years.at(-1)}`}`
    : `${layer.count.toLocaleString()} stations`
  if (layer.kind === 'sites') return `${layer.count.toLocaleString()} files`
  if (layer.kind === 'cells') return `${layer.count.toLocaleString()} cells`
  if (layer.kind === 'area') return 'approximate'
  return 'documented extent'
}


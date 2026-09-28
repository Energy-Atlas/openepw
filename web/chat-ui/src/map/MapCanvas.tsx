import { useEffect, useRef, useState } from 'react'
import type { ExpressionSpecification, Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { appearanceStyle, applyAppearance, applyLighting, applyScene, autoView3d, scenePitch, type SceneSettings } from './scene'
import { renderShadows } from './renderShadows'
import { availabilityFeatures } from './evidence'
import { HATCH_IMAGES, MAP_PALETTE, SHAPE_IMAGES, STATION_LABEL_ZOOM, catalogFeatures, catalogLayerSpecs, layerSwatch,
  legendRows } from './catalogLayers'
import { calloutEnd, placeLabels, type LabelInput, type PlacedLabel } from './labels'
import { InfoTip } from '../InfoTip'
import { layoutCallouts, type CalloutLine, type CalloutTag, type ProductAvailability } from './availabilityCallouts'
import { utcSceneTime } from './sun'
import { THEME } from '../theme'
import { MinimizeIcon, TickIcon } from '../icons'
import type { WeatherGeography } from '../geography'
import type { AvailabilitySummary, CatalogLayer, CatalogMap, PointAvailability } from '../types'

const initial: SceneSettings = {
  appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1,
  ...utcSceneTime(new Date()), lightIntensity: 100, diffusion: 25,
  haze: 20, shadows: true,
}

type MapPoint = { id?: string; name?: string; lat: number; lon: number; number?: number }

// isStyleLoaded() is also false while any tile is loading; overlays only need a parsed style.
function styleParsed(map: MapLibreMap | null): map is MapLibreMap {
  return Boolean(map?.getStyle())
}

export function MapCanvas({ location, candidates = [], geography, resolvedPoints = [], availability, catalogMap, years = [],
  pickMode = false, onExitPickMode, onPickPoint, onPickCandidate, onPickGeometry,
  pendingCandidate = null, onConfirmCandidate, productAvailability = null, selectedProducts = [], onToggleProduct,
  pointAvailability }: {
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
  pendingCandidate?: string | null
  onConfirmCandidate?: (id: string) => void
  /** Where each weather product is available, shown while a product is chosen. */
  productAvailability?: ProductAvailability | null
  /** Products ticked for download; clicking a tag toggles its product. */
  selectedProducts?: string[]
  onToggleProduct?: (option: string) => void
  /** Named-product availability at a point, for the hover card on the globe. */
  pointAvailability?: (lat: number, lon: number) => Promise<PointAvailability>
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
  const [labels, setLabels] = useState<PlacedLabel[]>([])
  const updateLabels = useRef<() => void>(() => {})
  const updateCallouts = useRef<() => void>(() => {})
  const updateMarkers = useRef<() => void>(() => {})
  // The hover card: where the cursor is on the globe, and cached availability per 0.1° cell.
  const [hover, setHover] = useState<{ x: number; y: number; key: string } | null>(null)
  const pointCache = useRef(new Map<string, PointAvailability | 'loading' | 'error'>())
  // The last place shown, kept on screen (dimmed) while the next place loads.
  const lastPoint = useRef<PointAvailability | null>(null)
  const [, setPointTick] = useState(0)
  const pointAvailabilityRef = useRef(pointAvailability)
  pointAvailabilityRef.current = pointAvailability
  const [markers, setMarkers] = useState<Array<{ id: string; x: number; y: number; label: string }>>([])
  const calloutBoxes = useRef<Array<{ x: number; y: number; width: number; height: number }>>([])
  const [callouts, setCallouts] = useState<{ tags: CalloutTag[]; lines: CalloutLine[] }>({ tags: [], lines: [] })
  const restorePopup = useRef<() => void>(() => {})
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
        // A click on the globe has no effect of its own; dragging still pans and rotates.
        doubleClickZoom: false,
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
      let labelFrame = 0
      const scheduleLabels = () => {
        if (labelFrame) return
        const next = window.requestAnimationFrame ?? ((callback: FrameRequestCallback) => window.setTimeout(callback, 16))
        labelFrame = next(() => { labelFrame = 0; updateCallouts.current(); updateLabels.current(); updateMarkers.current() }) as number
      }
      sceneMap.on('move', scheduleLabels)
      sceneMap.on('idle', () => { updateCallouts.current(); updateLabels.current(); updateMarkers.current() })
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
      let hoverTimer = 0
      const hideHover = () => { window.clearTimeout(hoverTimer); setHover(null) }
      sceneMap.on('mousemove', event => {
        const canvas = sceneMap.getCanvas()
        const overCandidate = sceneMap.getLayer('openepw-candidates')
          && sceneMap.queryRenderedFeatures(event.point, { layers: ['openepw-candidates'] }).length > 0
        canvas.style.cursor = overCandidate ? 'var(--oe-cursor-pointer)' : ''
        // Only on the globe itself: a point in space does not project back to where the cursor is.
        const back = sceneMap.project([event.lngLat.lng, event.lngLat.lat])
        if ((event.originalEvent as MouseEvent | undefined)?.buttons || !pointAvailabilityRef.current
            || Math.hypot(back.x - event.point.x, back.y - event.point.y) > 3) {
          hideHover()
          return
        }
        const lat = Math.round(event.lngLat.lat * 10) / 10
        const lon = Math.round((((event.lngLat.lng + 180) % 360 + 360) % 360 - 180) * 10) / 10
        const key = `${lat.toFixed(1)},${lon.toFixed(1)}`
        setHover({ x: event.point.x, y: event.point.y, key })
        window.clearTimeout(hoverTimer)
        if (pointCache.current.has(key)) return
        // Ask only once the cursor rests, so moving across the globe sends no requests.
        hoverTimer = window.setTimeout(() => {
          pointCache.current.set(key, 'loading')
          setPointTick(value => value + 1)
          void pointAvailabilityRef.current?.(lat, lon)
            .then(value => pointCache.current.set(key, value), () => pointCache.current.set(key, 'error'))
            .finally(() => setPointTick(value => value + 1))
        }, 80)
      })
      sceneMap.on('mouseout', hideHover)
      sceneMap.on('dragstart', hideHover)
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
          restorePopup.current()
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
        properties: { id: point.id ?? '', name: point.name ?? '', label: point.number ? String(point.number) : '',
          selected: false, pending: point.id === pendingCandidate } })),
      ...(location ? [{ type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [location.lon, location.lat] },
        properties: { id: location.id ?? '', name: location.name ?? '', label: '', selected: true, pending: false } }] : []),
    ]
    const highlighted: ExpressionSpecification = ['any', ['get', 'selected'], ['get', 'pending']]
    if (!sceneMap.getSource('openepw-candidates')) {
      sceneMap.addSource('openepw-candidates', { type: 'geojson', data: { type: 'FeatureCollection', features } })
      // Filled, numbered markers match the numbered options in chat; amber marks the chosen one.
      sceneMap.addLayer({ id: 'openepw-candidates', type: 'circle', source: 'openepw-candidates',
        paint: { 'circle-radius': ['case', ['get', 'pending'], 11, ['get', 'selected'], 7, 9],
          'circle-color': ['case', highlighted, MAP_PALETTE.HERO, MAP_PALETTE.CANDIDATE],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': ['case', highlighted, MAP_PALETTE.CANDIDATE, THEME.PAPER] } })
      sceneMap.addLayer({ id: 'openepw-candidate-numbers', type: 'symbol', source: 'openepw-candidates',
        layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 11,
          'text-allow-overlap': true, 'text-ignore-placement': true },
        paint: { 'text-color': ['case', highlighted, MAP_PALETTE.CANDIDATE, THEME.PAPER] } })
    } else {
      (sceneMap.getSource('openepw-candidates') as import('maplibre-gl').GeoJSONSource).setData({
        type: 'FeatureCollection', features,
      })
    }
  }, [candidates, location, pendingCandidate, styleEpoch])

  // A chosen option rotates the globe to it; off-screen targets zoom out, travel and zoom back in.
  const pending = candidates.find(point => point.id === pendingCandidate) ?? null
  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap || !pending) return
    const center: [number, number] = [pending.lon, pending.lat]
    const padding = { right: window.innerWidth > 650 ? 410 : 0 }
    if (sceneMap.getBounds().contains(center)) sceneMap.easeTo({ center, padding, duration: 700 })
    else sceneMap.flyTo({ center, zoom: sceneMap.getZoom(), padding, duration: 1800, essential: true })
  }, [pending?.id, pending?.lat, pending?.lon])

  const [popupAt, setPopupAt] = useState<{ x: number; y: number } | null>(null)
  // Minimizing hides the popup but keeps the selection; picking the marker again restores it.
  const [popupMinimized, setPopupMinimized] = useState(false)
  useEffect(() => setPopupMinimized(false), [pendingCandidate])
  restorePopup.current = () => setPopupMinimized(false)
  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap || !pending) { setPopupAt(null); return }
    const place = () => { const point = sceneMap.project([pending.lon, pending.lat]); setPopupAt({ x: point.x, y: point.y }) }
    place()
    sceneMap.on('move', place)
    return () => { sceneMap.off('move', place) }
  }, [pending?.id, pending?.lat, pending?.lon, styleEpoch])

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
      // Previewed places carry ids "place-N"; the number matches the chat list for text edits.
      const label = /^place-(\d+)$/.exec(point.id ?? '')?.[1] ?? ''
      features.push({ type: 'Feature', properties: { label },
        geometry: { type: 'Point', coordinates: [point.lon, point.lat] } })
    }
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    addPatternImages(sceneMap)
    if (!sceneMap.getSource('openepw-selection')) {
      sceneMap.addSource('openepw-selection', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-selection-fill', type: 'fill', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-pattern': 'oe-hatch-selection', 'fill-opacity': .6 } })
      sceneMap.addLayer({ id: 'openepw-selection-outline', type: 'line', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'line-color': MAP_PALETTE.HERO_LINE, 'line-width': 2 } })
      sceneMap.addLayer({ id: 'openepw-selection-points', type: 'circle', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Point'], paint: {
          'circle-radius': ['case', ['==', ['get', 'label'], ''], 4, 9], 'circle-color': MAP_PALETTE.HERO,
          'circle-stroke-width': 1.2, 'circle-stroke-color': MAP_PALETTE.CANDIDATE } })
      sceneMap.addLayer({ id: 'openepw-selection-numbers', type: 'symbol', source: 'openepw-selection',
        filter: ['==', ['geometry-type'], 'Point'],
        layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 10,
          'text-allow-overlap': true, 'text-ignore-placement': true },
        paint: { 'text-color': MAP_PALETTE.CANDIDATE } })
    } else {
      (sceneMap.getSource('openepw-selection') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [geography, resolvedPoints, styleEpoch])

  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap)) return
    const data = availabilityFeatures(availability)
    addPatternImages(sceneMap)
    if (!sceneMap.getSource('openepw-evidence')) {
      sceneMap.addSource('openepw-evidence', { type: 'geojson', data })
      sceneMap.addLayer({ id: 'openepw-evidence-fill', type: 'fill', source: 'openepw-evidence',
        paint: { 'fill-pattern': 'oe-hatch-region', 'fill-opacity': .18 } })
      sceneMap.addLayer({ id: 'openepw-evidence-line', type: 'line', source: 'openepw-evidence',
        paint: { 'line-color': ['get', 'color'], 'line-width': 1.1,
          'line-dasharray': [2, 2], 'line-opacity': .34 } })
    } else {
      (sceneMap.getSource('openepw-evidence') as import('maplibre-gl').GeoJSONSource).setData(data)
    }
  }, [availability, styleEpoch])

  updateLabels.current = () => {
    const sceneMap = map.current
    if (!sceneMap || !styleParsed(sceneMap) || sceneMap.getZoom() < STATION_LABEL_ZOOM) {
      setLabels(current => current.length ? [] : current)
      return
    }
    const sources = ([['noaa', MAP_PALETTE.OBSERVED], ['onebuilding', MAP_PALETTE.PUBLISHED]] as const)
      .filter(([id]) => !hiddenLayers.includes(id) && sceneMap.getLayer(`openepw-catalog-${id}-point`))
    const features = sources.length ? sceneMap.queryRenderedFeatures({
      layers: sources.map(([id]) => `openepw-catalog-${id}-point`) }) : []
    const size = { width: host.current?.clientWidth || window.innerWidth, height: host.current?.clientHeight || window.innerHeight }
    const markers: Array<{ x: number; y: number }> = []
    const items: LabelInput[] = []
    // While a product is chosen, only the stations it looked up keep their names.
    const matched = productAvailability?.locations.length ? new Set(productAvailability.locations.flatMap(item =>
      item.products.flatMap(product => product.station
        ? [`${product.layer}:${product.station.lon.toFixed(3)}:${product.station.lat.toFixed(3)}`] : []))) : null
    const seen = new Set<string>()
    for (const feature of features) {
      const [lon, lat] = (feature.geometry as GeoJSON.Point).coordinates
      const point = sceneMap.project([lon, lat])
      markers.push(point)
      const name = String(feature.properties?.name ?? '')
      const layer = feature.layer.id.includes('noaa') ? 'noaa' : 'onebuilding'
      if (matched && !matched.has(`${layer}:${lon.toFixed(3)}:${lat.toFixed(3)}`)) continue
      const color = layer === 'noaa' ? MAP_PALETTE.OBSERVED : MAP_PALETTE.PUBLISHED
      const key = `${color}:${name}:${lon.toFixed(4)}:${lat.toFixed(4)}`
      if (!name || seen.has(key)) continue
      seen.add(key)
      const text = name.length > 30 ? `${name.slice(0, 29)}…` : name
      const prefix = layer === 'noaa' ? 'NOAA' : 'One'
      items.push({ id: key, x: point.x, y: point.y, text, prefix, color,
        width: textWidth(text) + textWidth(prefix) + 24, height: 17 })
    }
    // Stations nearest the middle of the view win when space is short.
    items.sort((a, b) => Math.hypot(a.x - size.width / 2, a.y - size.height / 2)
      - Math.hypot(b.x - size.width / 2, b.y - size.height / 2))
    setLabels(placeLabels(items, markers, size, { obstacles: calloutBoxes.current }))
  }

  updateCallouts.current = () => {
    const sceneMap = map.current
    if (!sceneMap || !styleParsed(sceneMap) || !productAvailability?.locations.length) {
      calloutBoxes.current = []
      setCallouts(current => current.tags.length || current.lines.length ? { tags: [], lines: [] } : current)
      return
    }
    // Tags follow the legend toggles: a hidden source layer hides its products' tags too.
    const locations = productAvailability.locations.map(item => ({ ...item,
      products: item.products.filter(product => !hiddenLayers.includes(product.layer)) }))
    const size = { width: host.current?.clientWidth || window.innerWidth, height: host.current?.clientHeight || window.innerHeight }
    const next = layoutCallouts(locations, (lon, lat) => sceneMap.project([lon, lat]), textWidth, size)
    // Station names are placed after the tags and keep clear of them.
    calloutBoxes.current = next.tags.map(tag => ({ x: tag.x - 2, y: tag.y - 2, width: tag.width + 4, height: 21 }))
    setCallouts(next)
  }
  useEffect(() => { updateCallouts.current(); updateLabels.current() }, [productAvailability, hiddenLayers, styleEpoch])
  // Frame the locations with their looked-up stations once, so every station link is visible.
  const calloutPoints = (productAvailability?.locations ?? []).flatMap(item => [[item.lon, item.lat],
    ...item.products.flatMap(product => product.station ? [[product.station.lon, product.station.lat]] : [])])
  const calloutKey = JSON.stringify(calloutPoints)
  useEffect(() => {
    const sceneMap = map.current
    if (!sceneMap || !calloutPoints.length || typeof sceneMap.fitBounds !== 'function') return
    const lons = calloutPoints.map(point => point[0])
    const lats = calloutPoints.map(point => point[1])
    sceneMap.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], {
      padding: { top: 90, bottom: 90, left: 90, right: window.innerWidth > 650 ? 470 : 60 }, maxZoom: 12, duration: 900 })
  }, [calloutKey, styleEpoch])

  // The chosen locations are redrawn above the HTML station names and tags, which would
  // otherwise cover the canvas markers. Many points stay canvas-only to keep moves cheap.
  updateMarkers.current = () => {
    const sceneMap = map.current
    const points = location ? [{ ...location, id: location.id ?? 'location' }] : resolvedPoints
    if (!sceneMap || !styleParsed(sceneMap) || !points.length) {
      setMarkers(current => current.length ? [] : current)
      return
    }
    const size = { width: host.current?.clientWidth || window.innerWidth, height: host.current?.clientHeight || window.innerHeight }
    const placed = points.map((point, index) => {
      const at = sceneMap.project([point.lon, point.lat])
      return { id: `${point.id ?? index}`, x: at.x, y: at.y,
        label: location ? '' : /^place-(\d+)$/.exec(point.id ?? '')?.[1] ?? '' }
    }).filter(point => point.x >= -20 && point.y >= -20 && point.x <= size.width + 20 && point.y <= size.height + 20)
    setMarkers(placed.length <= 60 ? placed : [])
  }
  useEffect(() => { updateMarkers.current() }, [location?.lat, location?.lon, resolvedPoints, styleEpoch])

  const yearKey = years.join(',')
  // Hover availability depends on the chosen years.
  useEffect(() => { pointCache.current.clear() }, [yearKey])
  useEffect(() => {
    const sceneMap = map.current
    if (!styleParsed(sceneMap) || !catalogMap) return
    // Catalog context sits under the user's selection, candidates and drawing; broad extents lowest.
    const own = new Set(['openepw-selection-fill', 'openepw-drawing', 'openepw-candidates', 'openepw-evidence-fill'])
    const before = sceneMap.getStyle().layers.find(item => own.has(item.id))?.id
    const stack = ['extent', 'cells', 'area', 'sites', 'stations']
    const ordered = [...catalogMap.layers].sort((a, b) => stack.indexOf(a.kind) - stack.indexOf(b.kind))
    addPatternImages(sceneMap)
    for (const layer of ordered) {
      const id = `openepw-catalog-${layer.id}`
      const data = catalogFeatures(layer, layer.kind === 'stations' ? years : [])
      const source = sceneMap.getSource(id) as import('maplibre-gl').GeoJSONSource | undefined
      if (source) source.setData(data)
      else {
        sceneMap.addSource(id, { type: 'geojson', data })
        for (const spec of catalogLayerSpecs(layer, id)) {
          // A land-only fill sits under the basemap water layer, which then masks the oceans.
          const under = (spec as { metadata?: Record<string, unknown> }).metadata?.['openepw:before']
          sceneMap.addLayer(spec, typeof under === 'string' && sceneMap.getLayer(under) ? under : before)
        }
      }
      const visibility = hiddenLayers.includes(layer.id) ? 'none' : 'visible'
      for (const suffix of ['fill', 'line', 'point', 'label'])
        if (sceneMap.getLayer(`${id}-${suffix}`)) sceneMap.setLayoutProperty(`${id}-${suffix}`, 'visibility', visibility)
    }
    updateLabels.current()
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
      <div className="legend-head"><strong>Weather Product Coverage</strong>
        <InfoTip label="About these layers">
          <p>Dot = record · ring = approximate or candidate · hatch = source area · dashed = documented extent ·
            amber = your selection.</p>
          <p>Stage 1 catalog · {catalogMap.snapshot?.created_at.slice(0, 10) ?? 'bundled contracts'} · documentary,
            not point eligibility.</p>
          {catalogMap.unmapped.length > 0 && <p>No reviewed geometry: {catalogMap.unmapped
            .map(item => `${item.provider}/${item.dataset}`).join(', ')}.</p>}
          <p>Credits: NOAA NCEI ISD; OneBuilding.org; NLR NSRDB (CC BY 3.0 US); PVGIS © European Union/JRC;
            Copernicus ERA5 and Open-Meteo.</p>
        </InfoTip></div>
      {legendRows(catalogMap.layers).map(row => {
        // The ERA5-Land hatch stands for the merged extent row, as on the map.
        const swatch = layerSwatch(row.layers.find(layer => layer.id === 'era5-land') ?? row.layers[0])
        return <div key={row.ids.join()} className="scope-row">
          <label>
            <input type="checkbox" checked={!row.ids.every(id => hiddenLayers.includes(id))} onChange={() =>
              setHiddenLayers(current => row.ids.every(id => current.includes(id))
                ? current.filter(item => !row.ids.includes(item)) : [...new Set([...current, ...row.ids])])} />
            <i className={`swatch swatch-${swatch.shape}`} style={{ color: swatch.color }} />
            <span>{row.label}</span>
          </label>
          <InfoTip label={`About ${row.label}`}>
            {row.layers.map(layer => <p key={layer.id}><b>{layer.label}</b> · {layerCount(layer, years)}. {layer.caveat}
              {layer.evidence_dates.length ? ` Evidence ${layer.evidence_dates.at(-1)}.` : ''}</p>)}
          </InfoTip>
        </div>
      })}
    </aside>}
    {(callouts.tags.length > 0 || callouts.lines.length > 0) && <div className="availability-callouts"
      aria-label="Product availability at your locations" role="group">
      <svg width="100%" height="100%" aria-hidden="true">
        {callouts.lines.map(line => <line key={line.id} className={`station-link${selectedProducts.length &&
          !line.option.some(option => selectedProducts.includes(option)) ? ' dim' : ''}`} x1={line.x1} y1={line.y1}
          x2={line.x2} y2={line.y2} stroke={line.color} />)}
      </svg>
      {callouts.tags.map(tag => <button type="button" key={tag.id} data-option={tag.option}
        aria-pressed={selectedProducts.includes(tag.option)} disabled={!onToggleProduct}
        onClick={() => onToggleProduct?.(tag.option)}
        className={`availability-tag ${tag.status}${selectedProducts.length ? selectedProducts.includes(tag.option)
          ? ' chosen' : ' dim' : ''}`}
        title={tag.status === 'unknown' ? `${tag.text.slice(0, -2)}: not verified in the catalog; checked when planning`
          : `${tag.text}: listed in the catalog`}
        style={{ left: tag.x, top: tag.y, width: tag.width, ...(tag.status === 'unknown'
          ? { boxShadow: `inset 0 0 0 1.5px ${tag.color}, 0 1px 2px rgba(31, 31, 31, .25)` }
          : { background: tag.color, color: tag.textColor }) }}>{tag.text}</button>)}
    </div>}
    {labels.length > 0 && <div className="station-labels" aria-hidden="true">
      <svg className="station-callouts" width="100%" height="100%">
        {labels.filter(label => label.callout).map(label => {
          const end = calloutEnd(label)
          return <line key={label.id} x1={label.anchor.x} y1={label.anchor.y} x2={end.x} y2={end.y} stroke={label.color} />
        })}
      </svg>
      {labels.map(label => <span key={label.id} className="station-label"
        style={{ left: label.x, top: label.y, width: label.width, background: label.color }}>
        {label.prefix && <span className="station-prefix">{label.prefix}</span>}{label.text}</span>)}
    </div>}
    {hover && <PointCard hover={hover} data={pointCache.current.get(hover.key)} lastPoint={lastPoint}
      size={{ width: host.current?.clientWidth || window.innerWidth, height: host.current?.clientHeight || window.innerHeight }} />}
    {markers.length > 0 && <div className="location-markers" data-testid="location-markers" aria-hidden="true">
      {markers.map(marker => <span key={marker.id} className={`location-marker${marker.label ? ' numbered' : ''}`}
        style={{ left: marker.x, top: marker.y }}>{marker.label}</span>)}
    </div>}
    {pending && popupAt && !popupMinimized && <div className="candidate-popup" role="dialog" aria-label="Selected location"
      style={{ left: popupAt.x, top: popupAt.y }}>
      <span className="option-number" aria-hidden="true">{pending.number}</span>
      <strong>{pending.name}</strong>
      <button type="button" className="popup-minimize" aria-label="Minimize" title="Minimize"
        onClick={() => setPopupMinimized(true)}><MinimizeIcon /></button>
      <code>{pending.lat.toFixed(4)}, {pending.lon.toFixed(4)}</code>
      <button type="button" className="popup-confirm" aria-label="Confirm" title="Confirm"
        onClick={() => pending.id && onConfirmCandidate?.(pending.id)}><TickIcon /></button>
    </div>}
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

const STATUS_TEXT = { supported: 'listed in the catalog', unknown: 'checked when planning', none: 'not available here' }

/** Weather products at the cursor: a dot per product (green = listed here) and the station for station products. */
function PointCard({ hover, data: current, lastPoint, size }: { hover: { x: number; y: number; key: string }
  data: PointAvailability | 'loading' | 'error' | undefined; lastPoint: { current: PointAvailability | null }
  size: { width: number; height: number } }) {
  if (typeof current === 'object') lastPoint.current = current
  // While a new place loads, the previous rows stay (dimmed) rather than a blank card.
  const updating = typeof current !== 'object' && current !== 'error' && lastPoint.current !== null
  const data = updating ? lastPoint.current! : current
  // Open leftward before reaching the floating chat on the right, not only at the map's edge.
  const flipX = hover.x + 16 + 320 > size.width - (size.width > 650 ? 430 : 0)
  const flipY = hover.y > size.height * .55
  const [lat, lon] = hover.key.split(',')
  const groups = typeof data === 'object' ? (['actual', 'typical'] as const)
    .map(group => ({ group, rows: data.products.filter(row => row.group === group) })).filter(item => item.rows.length) : []
  return <section className={`point-card${updating ? ' updating' : ''}`} role="status" aria-label="Weather products here"
    style={{ left: hover.x + (flipX ? -16 : 16), top: hover.y + (flipY ? -16 : 16),
      transform: `translate(${flipX ? '-100%' : '0'}, ${flipY ? '-100%' : '0'})` }}>
    <header>{lat}°, {lon}°{typeof data === 'object' && data !== null && data.years_assumed ? ` · ${data.years.join(', ')}` : ''}</header>
    {data === undefined || data === 'loading' ? <p className="point-note">Checking the catalog…</p>
      : data === 'error' ? <p className="point-note">Availability could not be read.</p>
      : groups.map(({ group, rows }) => <div key={group}>
        <h3>{group === 'actual' ? 'Actual year' : 'Typical year'}</h3>
        {rows.map(row => <div key={row.id} className="point-row">
          <span className="point-name">{row.label}</span>
          {row.station && row.status !== 'none' && <span className="point-where">
            <span className="point-station">{row.station.name ?? 'station'}</span>
            {row.station.distance_km != null && <span className="point-km">{row.station.distance_km} km</span>}
          </span>}
          <i className={`point-dot ${row.status}`} role="img" aria-label={STATUS_TEXT[row.status]} />
        </div>)}
      </div>)}
  </section>
}

/** Marker shapes and polygon hatches; a style reload drops them, so each user adds them again. */
function addPatternImages(sceneMap: MapLibreMap) {
  for (const image of [...SHAPE_IMAGES, ...HATCH_IMAGES])
    if (!sceneMap.hasImage(image.name)) sceneMap.addImage(image.name, image, { pixelRatio: 2 })
}

let measureContext: CanvasRenderingContext2D | null | undefined
/** Pill text width in CSS pixels; falls back to an estimate where canvas is unavailable. */

function textWidth(text: string): number {
  if (measureContext === undefined) {
    try { measureContext = document.createElement('canvas').getContext('2d') } catch { measureContext = null }
    if (measureContext) measureContext.font = "500 10px Geist, system-ui, sans-serif"
  }
  return Math.ceil(measureContext ? measureContext.measureText(text).width : text.length * 5.8)
}

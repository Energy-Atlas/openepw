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
import { coverageBeforeIds, datasetColor } from './datasetColor'
import { GeometryToolbar } from './GeometryToolbar'
import { PointGlyph, type DatasetPointStatus } from './PointGlyph'
import { VertexHandles } from './VertexHandles'
import {
  applyShape,
  canFinish,
  editableShape,
  geometry,
  type DrawMode,
  type Position,
} from './selection'

class MapBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false }
  static getDerivedStateFromError() {
    return { error: true }
  }
  render() {
    return this.state.error ? (
      <div className="empty">
        3D map unavailable. Explore controls remain available in the stage panel.
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
  const coverageRequested = useRef(false)
  const state = useApp()
  const [style, setStyle] = useState<StyleSpecification | null>(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState<DrawMode>('point')
  const [drawing, setDrawing] = useState(false)
  const [vertices, setVertices] = useState<Position[]>([])
  // Editing reopens the applied geometry's vertices; drawing builds a new shape.
  const [editing, setEditing] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // The store owns which overlays are on (so discovery can enable them); opacity is local.
  const [opacities, setOpacities] = useState<Record<string, number>>({})
  const coverage: CoverageSetting[] = state.selectedCoverageIds.map((id) => ({
    id,
    // Light by default so an automatically enabled extent never hides the map.
    opacity: opacities[id] ?? 0.18,
  }))
  const [camera, setCamera] = useState({
    longitude: -76.5,
    latitude: 42.44,
    zoom: 4,
    pitch: 48,
    bearing: 0,
  })

  useEffect(() => {
    const controller = new AbortController()
    fetch('https://tiles.openfreemap.org/styles/positron', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw Error()
        return response.json()
      })
      .then(setStyle)
      .catch((reason) => {
        if (reason.name !== 'AbortError')
          setError('Basemap unavailable. Location selection remains usable.')
      })
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

  const locations = state.spatialPreview?.locations ?? []
  const movablePoint =
    state.stage === 'explore' &&
    !Array.isArray(state.draft.locations) &&
    'lat' in state.draft.locations
  const sourceLocations = (state.discovery?.candidates ?? [])
    .map((candidate) => candidate.source.location)
    .filter((location): location is Schemas['Location'] => !!location)
  const links = {
    type: 'FeatureCollection' as const,
    features:
      locations.length === 1
        ? sourceLocations.map((point) => ({
            type: 'Feature' as const,
            geometry: {
              type: 'LineString' as const,
              coordinates: [
                [locations[0].lon, locations[0].lat],
                [point.lon, point.lat],
              ],
            },
            properties: {},
          }))
        : [],
  }
  const shape = state.stage === 'explore' ? editableShape(state.draft.locations) : null
  // While drawing or editing a complete shape, the outline follows the working vertices.
  const workingOutline =
    (drawing || editing) && (mode === 'bbox' || mode === 'polygon') && canFinish(mode, vertices)
      ? draftOutline(geometry(mode, vertices))
      : null
  const outline = workingOutline ?? draftOutline(state.draft.locations)
  const activeCoverage = coverage.flatMap((setting) => {
    const layer = state.coverageLayers.find((item) => item.id === setting.id)
    return layer ? [{ layer, ...setting }] : []
  })
  const beforeIds = coverageBeforeIds(activeCoverage.map(({ layer }) => layer))

  function startEditing() {
    if (!shape) return
    setMode(shape.mode)
    setVertices(shape.vertices)
    setDrawing(false)
    setEditing(true)
    setError('')
  }

  function stopWorking() {
    setVertices([])
    setDrawing(false)
    setEditing(false)
  }

  function apply(points: Position[]) {
    try {
      const locations = editing
        ? applyShape(state.draft.locations, mode, points)
        : geometry(mode, points)
      const unchanged = JSON.stringify(locations) === JSON.stringify(state.draft.locations)
      stopWorking()
      setError('')
      if (unchanged) return
      run({ type: 'editQuery', patch: { locations: locations as never } })
      queueMicrotask(() => run({ type: 'previewSpatial' }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }
  // Keyboard alternatives while drawing: Enter finishes, Escape cancels. Capture phase with
  // preventDefault keeps the workspace Escape handler from also closing a drawer.
  useEffect(() => {
    if (!drawing && !editing) return
    const keydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (event.key === 'Enter' && vertices.length) {
        event.preventDefault()
        apply(vertices)
      } else if (event.key === 'Escape') {
        event.preventDefault()
        stopWorking()
      }
    }
    document.addEventListener('keydown', keydown, true)
    return () => document.removeEventListener('keydown', keydown, true)
  })

  function fitSelection() {
    // Camera flights are instant when the viewer prefers reduced motion.
    const duration = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : undefined
    if (locations.length === 1)
      ref.current?.flyTo({
        center: [locations[0].lon, locations[0].lat],
        zoom: 8,
        pitch: 48,
        duration,
      })
    else if (locations.length > 1)
      ref.current?.fitBounds(
        [
          [
            Math.min(...locations.map((point) => point.lon)),
            Math.min(...locations.map((point) => point.lat)),
          ],
          [
            Math.max(...locations.map((point) => point.lon)),
            Math.max(...locations.map((point) => point.lat)),
          ],
        ],
        { padding: 60, duration },
      )
  }
  function changeCoverage(next: CoverageSetting[]) {
    setOpacities((current) => ({
      ...current,
      ...Object.fromEntries(next.map((item) => [item.id, item.opacity])),
    }))
    run({ type: 'setCoverageSelection', ids: next.map((item) => item.id) })
  }

  return (
    <div className="map-page" ref={host}>
      {state.stage === 'explore' && (
        <GeometryToolbar
          mode={mode}
          drawing={drawing}
          vertices={vertices}
          onMode={setMode}
          onDrawing={setDrawing}
          onVertices={setVertices}
          onFinish={() => apply(vertices)}
          editable={Boolean(shape)}
          editing={editing}
          onEdit={startEditing}
          onCancel={stopWorking}
          onClear={() => {
            setVertices([])
            run({
              type: 'editQuery',
              patch: { locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 } },
            })
            queueMicrotask(() => run({ type: 'previewSpatial' }))
          }}
        />
      )}
      <CoverageControl
        layers={state.coverageLayers}
        selected={coverage}
        onChange={changeCoverage}
      />
      <button
        type="button"
        className="fit-selection"
        disabled={!locations.length}
        onClick={fitSelection}
      >
        Fit selection
      </button>
      {editing && (
        <div className="map-instruction">
          Drag a vertex handle, or focus one and use arrow keys (Shift moves farther) and Delete.
          Enter applies; Escape discards.
        </div>
      )}
      {drawing && (
        <div className="map-instruction">
          Click the globe to add{' '}
          {mode === 'bbox' ? 'two corners' : mode === 'point' ? 'a point' : 'vertices'}. Arrow keys
          nudge the latest vertex; Shift moves farther. Enter finishes; Escape cancels.
        </div>
      )}
      <MapViewGL
        ref={ref}
        {...camera}
        onMove={(event) => setCamera(event.viewState)}
        mapStyle={themed}
        onLoad={() => setLoaded(true)}
        onError={() =>
          setError('Some map tiles could not load. Weather requests are independent of map tiles.')
        }
        onClick={(event) => {
          // Marker clicks (vertex handles, point glyphs) reach the map too; they never add vertices.
          const target = event.originalEvent.target as Element | null
          if (!drawing || target?.closest('.maplibregl-marker')) return
          const next = [...vertices, [event.lngLat.lng, event.lngLat.lat] as Position]
          setVertices(next)
          if (mode === 'point' || (mode === 'bbox' && next.length === 2)) apply(next)
        }}
      >
        <NavigationControl visualizePitch />
        <Source
          id="dem"
          type="raster-dem"
          tiles={['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp']}
          encoding="terrarium"
          tileSize={512}
          maxzoom={16}
          attribution="© Mapterhorn"
        />
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
            paint={{
              'hillshade-shadow-color': appearance.chrome.textMuted,
              'hillshade-highlight-color': appearance.chrome.surface,
              'hillshade-exaggeration': 0.3,
            }}
          />
        </Source>
        {activeCoverage.map(({ layer, opacity }) =>
          layer.kind === 'vector' && layer.geometry ? (
            <Source
              key={layer.id}
              id={`coverage-${layer.id}`}
              type="geojson"
              data={layer.geometry as GeoJSONSourceSpecification['data']}
            >
              <Layer
                id={`coverage-fill-${layer.id}`}
                type="fill"
                beforeId={beforeIds[layer.id]}
                paint={{
                  'fill-color': datasetColor(layer.provider, layer.dataset, appearance),
                  'fill-opacity': opacity,
                }}
              />
              <Layer
                id={`coverage-line-${layer.id}`}
                type="line"
                beforeId={beforeIds[layer.id]}
                paint={{
                  'line-color': datasetColor(layer.provider, layer.dataset, appearance),
                  'line-width': 1.5,
                }}
              />
            </Source>
          ) : layer.kind === 'raster' && layer.tiles ? (
            <Source key={layer.id} id={`coverage-${layer.id}`} type="raster" tiles={[layer.tiles]}>
              <Layer
                id={`coverage-raster-${layer.id}`}
                type="raster"
                beforeId={beforeIds[layer.id]}
                paint={{ 'raster-opacity': opacity }}
              />
            </Source>
          ) : null,
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
        {(drawing || editing) && (
          <VertexHandles
            vertices={vertices}
            minimum={mode === 'polygon' ? 3 : mode === 'bbox' ? 2 : 1}
            onChange={setVertices}
          />
        )}
        {locations.map((location, index) => (
          <Marker
            key={location.id ?? `${location.lon}-${location.lat}`}
            longitude={location.lon}
            latitude={location.lat}
            anchor="center"
            draggable={movablePoint}
            onDragEnd={(event) => {
              if (
                !movablePoint ||
                Array.isArray(state.draft.locations) ||
                !('lat' in state.draft.locations)
              )
                return
              run({
                type: 'editQuery',
                patch: {
                  locations: {
                    ...state.draft.locations,
                    lat: event.lngLat.lat,
                    lon: event.lngLat.lng,
                  },
                },
              })
              queueMicrotask(() => run({ type: 'previewSpatial' }))
            }}
          >
            <PointGlyph
              label={location.name || `Sample ${index + 1}`}
              statuses={pointStatuses(state, location, appearance)}
              artifacts={pointArtifacts(state, location)}
            />
          </Marker>
        ))}
      </MapViewGL>
      <div className="map-caption">
        <span className="dot" /> Authoritative sampled point
        {state.selectedDatasets.length > 0 && (
          <ul className="map-legend" aria-label="Dataset colors">
            {state.selectedDatasets.map((selection) => (
              <li key={`${selection.provider}/${selection.dataset}/${selection.product_id ?? ''}`}>
                <i
                  style={{
                    background: datasetColor(selection.provider, selection.dataset, appearance),
                  }}
                />
                {selection.provider} · {selection.dataset}
              </li>
            ))}
            <li className="map-legend-key">
              Ring halves: red failed · grey credential-gated · amber no planned output · striped
              unknown
            </li>
          </ul>
        )}
        <span className="spacer" /> Terrain is context, not weather resolution.
      </div>
      {state.spatialPreview?.truncated && (
        <p className="map-limit" role="status">
          Showing {state.spatialPreview.returned_count.toLocaleString()} of{' '}
          {state.spatialPreview.total_count.toLocaleString()} authoritative samples.
        </p>
      )}
      {state.spatialPreview && !state.spatialPreview.executable && (
        <p className="map-limit blocking" role="alert">
          {state.spatialPreview.total_count.toLocaleString()} sampled locations exceed the limit of{' '}
          {state.spatialPreview.execution_limit.toLocaleString()} for this period. Increase spacing
          or reduce the area.
        </p>
      )}
      {error && (
        <p className="map-warning" role="status">
          {error}
        </p>
      )}
    </div>
  )
}

function draftOutline(locations: Schemas['WeatherRequest-Input']['locations']) {
  if (!Array.isArray(locations) && 'coordinates' in locations) return locations
  if (!Array.isArray(locations) && 'west' in locations)
    return {
      type: 'Polygon' as const,
      coordinates: [
        [
          [locations.west, locations.south],
          [locations.east, locations.south],
          [locations.east, locations.north],
          [locations.west, locations.north],
          [locations.west, locations.south],
        ],
      ],
    }
  return null
}

export function pointStatuses(
  state: ReturnType<typeof useApp.getState>,
  location: Schemas['Location'],
  appearance: Appearance,
): DatasetPointStatus[] {
  const discoveryCurrent = state.discoveryVersion === state.requestVersion
  const planCurrent =
    state.weatherPlanRequestVersion === state.requestVersion &&
    state.weatherPlanSelectionVersion === state.selectionVersion
  return state.selectedDatasets.map((selection) => {
    const candidate = state.discovery?.candidates.find(
      (item) =>
        item.source.provider === selection.provider &&
        item.source.dataset === selection.dataset &&
        (item.product_id ?? null) === (selection.product_id ?? null) &&
        (!item.location_id || item.location_id === location.id),
    )
    const artifact = artifactsForSelection(state, location, selection).some(
      (item) => item.media_type === 'application/vnd.energyplus.epw',
    )
    const currentJob = currentDownloadJob(state)
    const output = (state.weatherPlan?.outputs ?? []).find(
      (item) =>
        item.requested_location_id === location.id &&
        item.dataset_selection?.provider === selection.provider &&
        item.dataset_selection.dataset === selection.dataset &&
        (item.dataset_selection.product_id ?? null) === (selection.product_id ?? null),
    )
    const failed =
      Boolean(output) &&
      Boolean(currentJob) &&
      ['failed', 'partially_completed'].includes(currentJob!.state) &&
      !artifact
    const status: DatasetPointStatus['state'] = artifact
      ? 'complete'
      : !discoveryCurrent
        ? 'unknown'
        : !candidate
          ? 'unavailable'
          : failed
            ? 'failed'
            : candidate.requires_credentials?.length
              ? 'gated'
              : planCurrent && state.weatherPlan && !output
                ? 'incompatible'
                : 'selected'
    return {
      label: `${selection.provider} · ${selection.dataset}`,
      state: status,
      color: datasetColor(selection.provider, selection.dataset, appearance),
    }
  })
}

export function pointArtifacts(
  state: ReturnType<typeof useApp.getState>,
  location: Schemas['Location'],
): Artifact[] {
  const names = new Set(
    (state.weatherPlan?.outputs ?? [])
      .filter((output) => !location.id || output.requested_location_id === location.id)
      .map((output) => output.name),
  )
  const artifacts = currentDownloadJob(state)?.bundle?.weather ?? []
  if (names.size === 0) return []
  return artifacts.filter((artifact) => [...names].some((name) => artifact.path.endsWith(name)))
}

function artifactsForSelection(
  state: ReturnType<typeof useApp.getState>,
  location: Schemas['Location'],
  selection: Schemas['DatasetSelection'],
) {
  const names = new Set(
    (state.weatherPlan?.outputs ?? [])
      .filter(
        (output) =>
          (!location.id || output.requested_location_id === location.id) &&
          output.dataset_selection?.provider === selection.provider &&
          output.dataset_selection.dataset === selection.dataset &&
          (output.dataset_selection.product_id ?? null) === (selection.product_id ?? null),
      )
      .map((output) => output.name),
  )
  return (currentDownloadJob(state)?.bundle?.weather ?? []).filter((artifact) =>
    [...names].some((name) => artifact.path.endsWith(name)),
  )
}

function currentDownloadJob(state: ReturnType<typeof useApp.getState>) {
  return state.downloadJobs.find((job) => job.plan_hash === state.weatherPlan?.plan_hash)
}

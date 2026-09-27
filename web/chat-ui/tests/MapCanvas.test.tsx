import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatalogMap } from '../src/types'

// A parsed style whose tiles are still loading: MapLibre accepts sources and
// layers, but isStyleLoaded() stays false until every tile source finishes.
const fake = vi.hoisted(() => ({ maps: [] as Array<Record<string, unknown>> }))

vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'worker.js' }))
vi.mock('maplibre-gl', () => {
  class FakeMap {
    handlers = new Map<string, Array<() => void>>()
    sources = new Map<string, unknown>()
    layers: Array<{ id: string }> = []
    parsed = false
    constructor() { fake.maps.push(this as unknown as Record<string, unknown>) }
    on(event: string, handler: () => void) { this.handlers.set(event, [...this.handlers.get(event) ?? [], handler]) }
    once() {}
    off() {}
    inView = true
    getBounds() { return { contains: () => this.inView } }
    project([lon, lat]: [number, number]) { return { x: lon + 200, y: 300 - lat } }
    flyTo = vi.fn()
    emit(event: string) { for (const handler of this.handlers.get(event) ?? []) handler() }
    isStyleLoaded() { return false }
    getStyle() { return this.parsed ? { version: 8, sources: {}, layers: this.layers } : undefined }
    getSource(id: string) { return this.sources.get(id) }
    addSource(id: string, source: unknown) {
      if (!this.parsed) throw new Error('Style is not done loading.')
      this.sources.set(id, { ...source as object, setData: vi.fn() })
    }
    addLayer(layer: { id: string }) { this.layers.push(layer) }
    getLayer(id: string) { return this.layers.find(layer => layer.id === id) }
    images = new Set<string>()
    hasImage(name: string) { return this.images.has(name) }
    addImage(name: string) { this.images.add(name) }
    visibility = new Map<string, string>()
    setPaintProperty() {}
    setLayoutProperty(id: string, _name: string, value: string) { this.visibility.set(id, value) }
    setProjection() {}
    setLight() {}
    setSky() {}
    setTerrain() {}
    getTerrain() { return null }
    jumpTo() {}
    easeTo = vi.fn()
    getCenter() { return { lat: 18, lng: 0 } }
    zoom = 1.65
    getZoom() { return this.zoom }
    rendered: Array<Record<string, unknown>> = []
    queryRenderedFeatures() { return this.rendered }
    getPitch() { return 0 }
    getCanvas() { return document.createElement('canvas') }
    addControl() {}
    remove() {}
  }
  const api = { Map: FakeMap, NavigationControl: class {}, setWorkerUrl() {} }
  return { ...api, default: api }
})

const catalog: CatalogMap = {
  schema: 'catalog-map-1', snapshot: { generation_id: 'g', created_at: '2026-09-25T03:29:20+00:00' },
  layers: [
    { id: 'noaa', kind: 'stations', label: 'NOAA ISD stations', caveat: 'c', count: 2, evidence_dates: [],
      points: [[-76, 42, 'A', [[2016, 2018]]], [10, 10, 'B', [[2000, 2001]]]] },
    { id: 'era5', kind: 'extent', label: 'ERA5 global reanalysis', caveat: 'c', count: 2, evidence_dates: [],
      bounds: [-180, -89, 180, 89] },
  ],
  unmapped: [],
}

describe('map canvas overlays', () => {
  beforeEach(() => { fake.maps.length = 0; vi.stubGlobal('WebGLRenderingContext', function WebGL() {}) })
  afterEach(() => vi.unstubAllGlobals())

  it('draws catalog layers with toggles once the style is parsed even while tiles are still loading', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    render(<MapCanvas catalogMap={catalog} years={[2017]} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; emit(event: string): void;
      getSource(id: string): unknown; getLayer(id: string): unknown; visibility: Map<string, string> }
    map.parsed = true
    map.emit('style.load')
    await waitFor(() => expect(map.getSource('openepw-catalog-noaa')).toBeTruthy())
    expect(map.getLayer('openepw-catalog-noaa-point')).toBeTruthy()
    expect(map.getLayer('openepw-catalog-era5-line')).toBeTruthy()
    expect(map.getLayer('openepw-catalog-era5-fill')).toBeFalsy()
    expect(map.getSource('openepw-evidence')).toBeTruthy()
    expect(screen.getByLabelText('Data availability scope')).toHaveTextContent('1 reporting 2017')
    fireEvent.click(screen.getByRole('checkbox', { name: /NOAA ISD stations/ }))
    await waitFor(() => expect(map.visibility.get('openepw-catalog-noaa-point')).toBe('none'))
    expect(map.getSource('openepw-candidates')).toBeTruthy()
    expect(map.getSource('openepw-selection')).toBeTruthy()
  })

  it('previews a chosen candidate with a popup and only rotates when it is already in view', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    const candidates = [{ id: 'ma', name: 'Cambridge, Massachusetts', lat: 42.37, lon: -71.11, number: 1 },
      { id: 'uk', name: 'Cambridge, England', lat: 52.2, lon: 0.12, number: 2 }]
    const confirm = vi.fn()
    const { rerender } = render(<MapCanvas candidates={candidates} pendingCandidate={null} onConfirmCandidate={confirm} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; inView: boolean; emit(event: string): void;
      easeTo: ReturnType<typeof vi.fn>; flyTo: ReturnType<typeof vi.fn> }
    map.parsed = true
    map.emit('style.load')
    rerender(<MapCanvas candidates={candidates} pendingCandidate="uk" onConfirmCandidate={confirm} />)
    const popup = await screen.findByRole('dialog', { name: 'Selected location' })
    expect(popup).toHaveTextContent('Cambridge, England')
    expect(popup).toHaveTextContent('52.2000, 0.1200')
    expect(map.easeTo).toHaveBeenCalledWith(expect.objectContaining({ center: [0.12, 52.2] }))
    expect(map.flyTo).not.toHaveBeenCalled()
    map.inView = false
    rerender(<MapCanvas candidates={candidates} pendingCandidate="ma" onConfirmCandidate={confirm} />)
    await waitFor(() => expect(map.flyTo).toHaveBeenCalledWith(expect.objectContaining({ center: [-71.11, 42.37] })))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(confirm).toHaveBeenCalledWith('ma')
  })

  it('numbers previewed place points to match the chat list', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    render(<MapCanvas resolvedPoints={[{ id: 'place-1', lat: 42.36, lon: -71.06 }, { id: 'place-2', lat: 39.74, lon: -104.98 }]} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; emit(event: string): void;
      getSource(id: string): { data: GeoJSON.FeatureCollection } | undefined; getLayer(id: string): unknown }
    map.parsed = true
    map.emit('style.load')
    await waitFor(() => expect(map.getSource('openepw-selection')).toBeTruthy())
    expect(map.getLayer('openepw-selection-numbers')).toBeTruthy()
    expect(map.getSource('openepw-selection')!.data.features.map(feature => feature.properties?.label)).toEqual(['1', '2'])
  })

  it('draws station names as pills from zoom 8.5 and callouts when crowded', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    const catalogWithNames: CatalogMap = { ...catalog, layers: [catalog.layers[0],
      { id: 'onebuilding', kind: 'sites', label: 'OneBuilding', caveat: 'c', count: 1, evidence_dates: [], points: [] }] }
    render(<MapCanvas catalogMap={catalogWithNames} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; zoom: number; rendered: unknown[]; emit(event: string): void }
    map.parsed = true
    map.emit('style.load')
    const feature = (name: string, lon: number, lat: number, layer: string) =>
      ({ properties: { name }, geometry: { type: 'Point', coordinates: [lon, lat] }, layer: { id: layer } })
    map.rendered = [feature('LOGAN INTL', 200, 200, 'openepw-catalog-noaa-point'),
      feature('Boston Logan', 201, 201, 'openepw-catalog-onebuilding-point'),
      feature('Hanscom', 203, 199, 'openepw-catalog-noaa-point')]
    map.emit('idle')
    expect(document.querySelectorAll('.station-label')).toHaveLength(0)       // globe zoom
    map.zoom = 8.2
    map.emit('idle')
    expect(document.querySelectorAll('.station-label')).toHaveLength(0)       // still below 8.5
    map.zoom = 8.6
    map.emit('idle')
    await waitFor(() => expect(document.querySelectorAll('.station-label')).toHaveLength(3))
    expect([...document.querySelectorAll('.station-label')].map(node => node.textContent)).toContain('Boston Logan')
    expect(document.querySelectorAll('.station-callouts line').length).toBeGreaterThan(0)
  })
})

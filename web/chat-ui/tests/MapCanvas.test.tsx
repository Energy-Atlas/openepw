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
    visibility = new Map<string, string>()
    setPaintProperty() {}
    setLayoutProperty(id: string, _name: string, value: string) { this.visibility.set(id, value) }
    setProjection() {}
    setLight() {}
    setSky() {}
    setTerrain() {}
    getTerrain() { return null }
    jumpTo() {}
    easeTo() {}
    getCenter() { return { lat: 18, lng: 0 } }
    getZoom() { return 1.65 }
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
    expect(map.getLayer('openepw-catalog-era5-fill')).toBeTruthy()
    expect(map.getSource('openepw-evidence')).toBeTruthy()
    expect(screen.getByLabelText('Data availability scope')).toHaveTextContent('1 reporting 2017')
    fireEvent.click(screen.getByRole('checkbox', { name: /NOAA ISD stations/ }))
    await waitFor(() => expect(map.visibility.get('openepw-catalog-noaa-point')).toBe('none'))
    expect(map.getSource('openepw-candidates')).toBeTruthy()
    expect(map.getSource('openepw-selection')).toBeTruthy()
  })
})

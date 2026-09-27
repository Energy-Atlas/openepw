import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatalogScopes } from '../src/types'

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
    setPaintProperty() {}
    setLayoutProperty() {}
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

const scopes: CatalogScopes = {
  snapshot: { generation_id: 'g', created_at: '2026-09-25T03:29:20+00:00' },
  scopes: [{ provider: 'cds', dataset: 'reanalysis-era5-land', footprint: [0, -89, 360, 89],
    longitude_convention: '0_360', evidence_bases: ['inventory'], evidence_dates: ['2026-09-23'] }],
  unmapped: [],
}

describe('map canvas overlays', () => {
  beforeEach(() => { fake.maps.length = 0; vi.stubGlobal('WebGLRenderingContext', function WebGL() {}) })
  afterEach(() => vi.unstubAllGlobals())

  it('draws catalog scopes once the style is parsed even while tiles are still loading', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    render(<MapCanvas catalogScopes={scopes} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; emit(event: string): void;
      getSource(id: string): unknown; getLayer(id: string): unknown }
    map.parsed = true
    map.emit('style.load')
    await waitFor(() => expect(map.getSource('openepw-evidence')).toBeTruthy())
    expect(map.getLayer('openepw-evidence-fill')).toBeTruthy()
    expect(map.getLayer('openepw-evidence-line')).toBeTruthy()
    expect(map.getSource('openepw-candidates')).toBeTruthy()
    expect(map.getSource('openepw-selection')).toBeTruthy()
  })
})

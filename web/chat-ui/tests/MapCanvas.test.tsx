import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CatalogMap } from '../src/types'

// A parsed style whose tiles are still loading: MapLibre accepts sources and
// layers, but isStyleLoaded() stays false until every tile source finishes.
const fake = vi.hoisted(() => ({ maps: [] as Array<Record<string, unknown>> }))

vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'worker.js' }))
vi.mock('maplibre-gl', () => {
  class FakeMap {
    handlers = new Map<string, Array<(event?: unknown) => void>>()
    options: Record<string, unknown>
    sources = new Map<string, unknown>()
    layers: Array<{ id: string }> = []
    parsed = false
    constructor(options: Record<string, unknown>) { this.options = options; fake.maps.push(this as unknown as Record<string, unknown>) }
    on(event: string, handler: (event?: unknown) => void) { this.handlers.set(event, [...this.handlers.get(event) ?? [], handler]) }
    once() {}
    off() {}
    inView = true
    getBounds() { return { contains: () => this.inView } }
    project([lon, lat]: [number, number]) { return { x: lon + 200, y: 300 - lat } }
    flyTo = vi.fn()
    emit(event: string, payload?: unknown) { for (const handler of this.handlers.get(event) ?? []) handler(payload) }
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
    fitBounds = vi.fn()
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
    const legend = screen.getByLabelText('Data availability scope')
    expect(legend).toHaveTextContent('Weather Product Coverage')
    expect(legend).not.toHaveTextContent('1 reporting 2017')                       // names only
    const about = within(legend).getByRole('button', { name: 'About NOAA ISD stations' })
    fireEvent.mouseEnter(about)
    expect(screen.getByRole('tooltip')).toHaveTextContent('1 reporting 2017')
    fireEvent.mouseLeave(about)
    fireEvent.mouseEnter(within(legend).getByRole('button', { name: 'About these layers' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Credits')
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
    const popup2 = screen.getByRole('dialog', { name: 'Selected location' })
    const minimize = within(popup2).getByRole('button', { name: 'Minimize' })
    expect(minimize.textContent).toBe('')
    fireEvent.click(within(popup2).getByRole('button', { name: 'Confirm' }))
    expect(confirm).toHaveBeenCalledWith('ma')
    fireEvent.click(minimize)
    expect(screen.queryByRole('dialog', { name: 'Selected location' })).not.toBeInTheDocument()
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
    const { rerender } = render(<MapCanvas catalogMap={catalogWithNames} />)
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
    expect([...document.querySelectorAll('.station-label')].map(node => node.textContent)).toContain('OneBoston Logan')
    expect([...document.querySelectorAll('.station-prefix')].map(node => node.textContent).sort())
      .toEqual(['NOAA', 'NOAA', 'One'])                                     // source prefix inside each name pill
    expect(document.querySelectorAll('.station-callouts line').length).toBeGreaterThan(0)
    // While a product is chosen only the looked-up stations keep their names.
    const availability = { years: [2025], years_assumed: true, omitted_locations: 0, locations: [{ index: 0,
      lat: 199, lon: 202, products: [{ option: 'noaa-isd', layer: 'noaa', tag: 'NOAA ISD', status: 'supported' as const,
        station: { lat: 200, lon: 200, name: 'LOGAN INTL', distance_km: 3 } }] }] }
    rerender(<MapCanvas catalogMap={catalogWithNames} productAvailability={availability} />)
    map.emit('idle')
    await waitFor(() => expect([...document.querySelectorAll('.station-label')].map(node => node.textContent))
      .toEqual(['NOAALOGAN INTL']))
  })

  it('tags each product at the location and links a looked-up station with a moving dashed line', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    const availability = { years: [2025], years_assumed: true, omitted_locations: 0, locations: [{ index: 0,
      lat: 42, lon: -76, name: 'Ithaca', products: [
        { option: 'era5-openmeteo', layer: 'era5', tag: 'ERA5 · Open-Meteo', status: 'supported' as const },
        { option: 'nsrdb-actual', layer: 'nsrdb', tag: 'NSRDB actual year', status: 'unknown' as const },
        { option: 'noaa-isd', layer: 'noaa', tag: 'NOAA ISD', status: 'supported' as const,
          station: { lat: 40, lon: -60, name: 'Airport', distance_km: 5.2 } }] }] }
    const toggle = vi.fn()
    const { rerender } = render(<MapCanvas catalogMap={catalog} productAvailability={availability} onToggleProduct={toggle} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; emit(event: string): void }
    map.parsed = true
    map.emit('style.load')
    const group = await screen.findByRole('group', { name: 'Product availability at your locations' })
    const tags = [...group.querySelectorAll<HTMLElement>('.availability-tag')]
    expect(tags.map(tag => tag.textContent)).toEqual(['ERA5 · Open-Meteo', 'NSRDB actual year ?', 'NOAA ISD · 5.2 km'])
    expect(tags[0].style.left).toBe(tags[1].style.left)                     // left aligned at the location
    expect(tags[1]).toHaveClass('unknown')
    expect((map as unknown as { fitBounds: ReturnType<typeof vi.fn> }).fitBounds).toHaveBeenCalledWith(
      [[-76, 40], [-60, 42]], expect.objectContaining({ maxZoom: 12 }))       // location and station in view
    const link = group.querySelector('line.station-link')!
    expect([link.getAttribute('x1'), link.getAttribute('y1'), link.getAttribute('x2'), link.getAttribute('y2')])
      .toEqual(['124', '258', '140', '260'])                               // from the location to the station
    fireEvent.click(group.querySelector('[data-option="noaa-isd"]')!)
    expect(toggle).toHaveBeenCalledWith('noaa-isd')                          // a tag click toggles its product
    rerender(<MapCanvas catalogMap={catalog} productAvailability={availability} selectedProducts={['noaa-isd']}
      onToggleProduct={toggle} />)
    expect(group.querySelector('[data-option="noaa-isd"]')).toHaveAttribute('aria-pressed', 'true')
    expect(group.querySelector('[data-option="noaa-isd"]')).toHaveClass('chosen')
    expect(group.querySelector('[data-option="era5-openmeteo"]')).toHaveClass('dim')
    fireEvent.click(screen.getByRole('checkbox', { name: /NOAA ISD stations/ }))
    await waitFor(() => expect(group.querySelector('[data-option="noaa-isd"]')).toBeNull())
    expect(group.querySelector('line.station-link')).toBeNull()
  })

  it('draws the chosen locations above the station names and availability tags', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    const points = [{ id: 'place-1', lat: 42, lon: -76 }, { id: 'place-2', lat: 40, lon: -60 }]
    render(<MapCanvas catalogMap={catalog} resolvedPoints={points} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; emit(event: string): void }
    map.parsed = true
    map.emit('style.load')
    map.emit('idle')
    const layer = await screen.findByTestId('location-markers')
    const markers = [...layer.querySelectorAll<HTMLElement>('.location-marker')]
    expect(markers.map(marker => [marker.style.left, marker.style.top, marker.textContent]))
      .toEqual([['124px', '258px', '1'], ['140px', '260px', '2']])        // projected, numbered like the list
    const overlays = [...document.querySelectorAll('.map-canvas > div')].map(node => node.className)
    expect(overlays.indexOf('location-markers')).toBeGreaterThan(overlays.indexOf('station-labels'))
  })

  it('shows product availability under the cursor on the globe, and a click does nothing else', async () => {
    const { MapCanvas } = await import('../src/map/MapCanvas')
    const pointAvailability = vi.fn(async () => ({ lat: 42, lon: -76, years: [2025], years_assumed: true, products: [
      { id: 'era5-openmeteo', label: 'ERA5 actual year · Open-Meteo', group: 'actual' as const, status: 'supported' as const },
      { id: 'nsrdb-actual', label: 'NSRDB actual year · GOES v4', group: 'actual' as const, status: 'unknown' as const },
      { id: 'noaa-isd', label: 'NOAA ISD station observations', group: 'actual' as const, status: 'supported' as const,
        station: { lat: 42.1, lon: -76.2, name: 'ITHACA TOMPKINS REGIONAL AIRPORT', distance_km: 5.2 } },
      { id: 'pvgis-tmy', label: 'PVGIS TMY 5.3 · SARAH3', group: 'typical' as const, status: 'none' as const }] }))
    render(<MapCanvas catalogMap={catalog} pointAvailability={pointAvailability} />)
    await waitFor(() => expect(fake.maps).toHaveLength(1))
    const map = fake.maps[0] as unknown as { parsed: boolean; options: Record<string, unknown>; emit(event: string, payload?: unknown): void }
    expect(map.options.doubleClickZoom).toBe(false)                          // clicks do not zoom
    map.parsed = true
    map.emit('style.load')
    const move = (x: number, y: number, lng: number, lat: number) => map.emit('mousemove',
      { point: { x, y }, lngLat: { lng, lat }, originalEvent: { buttons: 0 } })
    move(124, 258, -76, 42)                                                     // on the globe
    const card = await screen.findByRole('status', { name: 'Weather products here' })
    await waitFor(() => expect(card).toHaveTextContent('ERA5 actual year · Open-Meteo'))
    expect(pointAvailability).toHaveBeenCalledWith(42, -76)
    const rows = [...card.querySelectorAll('.point-row')]
    expect(rows.map(row => row.querySelector('.point-dot')!.className)).toEqual([
      'point-dot supported', 'point-dot unknown', 'point-dot supported', 'point-dot none'])
    expect(rows[2].querySelector('.point-station')!.textContent).toBe('ITHACA TOMPKINS REGIONAL AIRPORT')
    expect(rows[2]).toHaveTextContent('5.2 km')
    move(600, 20, -76, 42)                                                      // off the globe, in space
    await waitFor(() => expect(screen.queryByRole('status', { name: 'Weather products here' })).not.toBeInTheDocument())
    move(124, 258, -76, 42)
    await screen.findByRole('status', { name: 'Weather products here' })
    expect(pointAvailability).toHaveBeenCalledTimes(1)                          // cached for this place
    const clear = window.innerWidth - (window.innerWidth > 650 ? 430 : 0)          // left of the chat panel
    expect(124 + 16 + 320 <= clear ? card.style.transform.startsWith('translate(0') : true).toBe(true)
    move(clear - 100, 258, clear - 300, 42)                                     // near the chat: opens leftward
    await waitFor(() => expect(screen.getByRole('status', { name: 'Weather products here' }).style.transform)
      .toContain('-100%'))
    map.emit('mouseout')
    await waitFor(() => expect(screen.queryByRole('status', { name: 'Weather products here' })).not.toBeInTheDocument())
  })
})

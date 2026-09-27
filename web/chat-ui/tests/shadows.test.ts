import { describe, expect, it } from 'vitest'
import { projectShadowRing, roofShadow, terrainOccluded } from '../src/map/shadows'

describe('decorative geometric shadows', () => {
  it('projects a 10 m roof west when the sun is due east at 45 degrees', () => {
    const footprint: [number, number][] = [[0, 0], [0.001, 0], [0.001, 0.001], [0, 0]]
    const shadow = projectShadowRing(footprint, 10, { elevationDeg: 45, azimuthDeg: 90 })
    expect(shadow).not.toBeNull()
    expect(shadow![0][0]).toBeCloseTo(-10 / 111_320, 5)
    expect(shadow![0][1]).toBeCloseTo(0, 5)
  })

  it('does not draw a direct solar shadow at night', () => {
    expect(projectShadowRing([[0, 0], [0.001, 0], [0, 0]], 10,
      { elevationDeg: -2, azimuthDeg: 90 })).toBeNull()
  })

  it('casts a taller building onto a lower neighboring roof', () => {
    const source = { ring: [[0, 0], [0.0001, 0], [0.0001, 0.0001], [0, 0.0001], [0, 0]] as [number, number][], height: 20 }
    const target = { ring: [[-0.00014, 0], [-0.00004, 0], [-0.00004, 0.0001], [-0.00014, 0.0001], [-0.00014, 0]] as [number, number][], height: 5 }
    const shade = roofShadow(source, target, { elevationDeg: 45, azimuthDeg: 90 })
    expect(shade.length).toBeGreaterThan(0)
    expect(shade[0].height).toBe(5)
    expect(roofShadow(target, source, { elevationDeg: 45, azimuthDeg: 90 })).toEqual([])
  })

  it('marks a low terrain cell in the shadow of a higher ridge', () => {
    const sample = (east: number, _north: number) => east > 5 && east < 20 ? 30 : 0
    expect(terrainOccluded(0, 0, sample, { elevationDeg: 20, azimuthDeg: 90 }, 50)).toBe(true)
    expect(terrainOccluded(0, 0, () => 0, { elevationDeg: 20, azimuthDeg: 90 }, 50)).toBe(false)
  })
})

describe('shadow renderer state', () => {
  it('reports the real pause reason while tiles of a parsed style are still loading', async () => {
    const { renderShadows } = await import('../src/map/renderShadows')
    const loadingTiles = { isStyleLoaded: () => false, getStyle: () => ({ version: 8, sources: {}, layers: [] }),
      getLayer: () => undefined, getZoom: () => 1.6 } as unknown as import('maplibre-gl').Map
    const settings = { appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1, dayOfYear: 172,
      utcMinutes: 720, lightIntensity: 100, diffusion: 25, haze: 20, shadows: true } as const
    expect(renderShadows(loadingTiles, settings)).toBe('Shadows paused in flat view.')
    expect(renderShadows(loadingTiles, { ...settings, view3d: true })).toBe('Zoom closer for district shadows.')
  })
})

describe('district shadow status', () => {
  function district(tilesLoaded: boolean) {
    const sources = new Map<string, unknown>()
    return { isStyleLoaded: () => false, getStyle: () => ({ version: 8, sources: {}, layers: [] }),
      getZoom: () => 15.5, getCenter: () => ({ lat: 40.015, lng: -105.27 }), getTerrain: () => null,
      getSource: (id: string) => sources.get(id), addSource: (id: string, source: unknown) => sources.set(id, source),
      getLayer: () => undefined, addLayer() {}, setLayoutProperty() {},
      areTilesLoaded: () => tilesLoaded } as unknown as import('maplibre-gl').Map
  }
  const daylight = { appearance: 'light', view3d: true, terrain: false, terrainExaggeration: 1, dayOfYear: 270,
    utcMinutes: 960, lightIntensity: 100, diffusion: 25, haze: 20, shadows: true } as const

  it('does not call buildings unavailable while district tiles are still loading', async () => {
    const { renderShadows } = await import('../src/map/renderShadows')
    expect(renderShadows(district(false), daylight)).toBe('Loading district tiles for shadows.')
    expect(renderShadows(district(true), daylight))
      .toBe('Building geometry unavailable at this location; terrain shadows may still appear.')
  })
})

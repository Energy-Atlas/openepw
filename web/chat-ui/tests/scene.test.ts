import { describe, expect, it, vi } from 'vitest'
import { appearanceStyle, appearanceTokens, applyScene, autoView3d, scenePitch, type SceneSettings } from '../src/map/scene'

const defaults: SceneSettings = {
  appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1,
  dayOfYear: 172, utcMinutes: 960, lightIntensity: 100, diffusion: 25,
  haze: 20, shadows: true,
}

describe('map scene', () => {
  it('has six distinct appearance choices', () => {
    expect(new Set((['light', 'dark', 'monochrome', 'landform', 'clean', 'engineering'] as const)
      .map(appearance => appearanceTokens[appearance].building)).size).toBe(6)
    expect(appearanceStyle('engineering')).toBe(appearanceStyle('dark'))
  })

  it('tilts only in the 3D view', () => {
    expect(scenePitch(defaults)).toBe(0)
    expect(scenePitch({ ...defaults, view3d: true })).toBe(50)
  })

  it('keeps terrain paused in flat view and restores globe projection', () => {
    const map = { setProjection: vi.fn(), setTerrain: vi.fn(), getSource: vi.fn(),
      getLayer: vi.fn(), getStyle: vi.fn(() => ({ layers: [] })) }
    applyScene(map as never, defaults)
    expect(map.setProjection).toHaveBeenCalledWith({ type: 'globe' })
    expect(map.setTerrain).toHaveBeenCalledWith(null)
  })

  it('adds decorative basemap buildings and DEM hillshade in 3D', () => {
    const map = {
      setProjection: vi.fn(), setTerrain: vi.fn(), setLight: vi.fn(), setSky: vi.fn(),
      getSource: vi.fn((id: string) => id === 'openmaptiles' ? {} : undefined),
      addSource: vi.fn(), getLayer: vi.fn(), addLayer: vi.fn(), setLayoutProperty: vi.fn(), setPaintProperty: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [{ id: 'base-building', 'source-layer': 'building', layout: { visibility: 'visible' } }] })),
      getCenter: vi.fn(() => ({ lat: 42.35, lng: -71.07 })),
    }
    applyScene(map as never, { ...defaults, view3d: true, terrain: true })
    expect(map.addSource).toHaveBeenCalledWith('openepw-terrain', expect.objectContaining({ encoding: 'terrarium' }))
    expect(map.addLayer).toHaveBeenCalledWith(expect.objectContaining({
      id: 'openepw-buildings', type: 'fill-extrusion', 'source-layer': 'building',
    }))
    expect(map.setTerrain).toHaveBeenCalledWith({ source: 'openepw-terrain', exaggeration: 1 })
    expect(map.setLight).toHaveBeenCalledWith(expect.objectContaining({ anchor: 'map' }))
    expect(map.setLayoutProperty).toHaveBeenCalledWith('base-building', 'visibility', 'none')
  })
})

describe('automatic district 3D', () => {
  it('enters 3D at district zoom and leaves it only after zooming back out', () => {
    expect(autoView3d(1.6, false)).toBe(false)
    expect(autoView3d(14, false)).toBe(true)
    expect(autoView3d(13.5, true)).toBe(true)
    expect(autoView3d(13.5, false)).toBe(false)
    expect(autoView3d(12.9, true)).toBe(false)
  })
})

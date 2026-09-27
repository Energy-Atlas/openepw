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

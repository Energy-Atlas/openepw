import { describe, expect, it } from 'vitest'
import { solarPosition } from '../src/map/sun'

describe('display-only solar position', () => {
  it('places the sun high over the equator around equinox noon and below the horizon at midnight', () => {
    expect(solarPosition(80, 720, 0, 0).elevationDeg).toBeGreaterThan(85)
    expect(solarPosition(80, 0, 0, 0).elevationDeg).toBeLessThan(-80)
  })
})

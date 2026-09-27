import { describe, expect, it } from 'vitest'
import { solarPosition, utcSceneTime } from '../src/map/sun'

describe('display-only solar position', () => {
  it('places the sun high over the equator around equinox noon and below the horizon at midnight', () => {
    expect(solarPosition(80, 720, 0, 0).elevationDeg).toBeGreaterThan(85)
    expect(solarPosition(80, 0, 0, 0).elevationDeg).toBeLessThan(-80)
  })

  it('uses UTC date and time even when the browser timezone differs', () => {
    expect(utcSceneTime(new Date('2024-03-01T23:45:00-05:00'))).toEqual({
      dayOfYear: 62, utcMinutes: 285,
    })
  })

  it('changes local sunlight when longitude changes under one UTC clock', () => {
    const noon = solarPosition(80, 720, 0, 0)
    const midnight = solarPosition(80, 720, 0, 180)
    expect(noon.elevationDeg).toBeGreaterThan(85)
    expect(midnight.elevationDeg).toBeLessThan(-80)
  })
})

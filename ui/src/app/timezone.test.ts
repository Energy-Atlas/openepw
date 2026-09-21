import { expect, it } from 'vitest'
import { followOffset, formatOffset, nominalOffsetMinutes, offsetMismatch } from './timezone'
import { geometry } from '../features/map/selection'

it('matches the backend longitude-based nominal offset, halves rounding up', () => {
  // Same cases as tests/unit/test_spatial.py::test_sampled_points_can_use_longitude_based_standard_time
  expect([-76.5, -7.5, 7.5, 0, 179.9, -179.9].map(nominalOffsetMinutes)).toEqual([
    -300, 0, 60, 0, 720, -720,
  ])
})

it('formats offsets and flags ones an hour or more from the longitude', () => {
  expect([0, -300, 330, 60].map(formatOffset)).toEqual(['UTC', 'UTC−5', 'UTC+5:30', 'UTC+1'])
  expect(offsetMismatch(0, -76.5)).toBe(true)
  expect(offsetMismatch(-300, -76.5)).toBe(false)
  expect(offsetMismatch(-240, -76.5)).toBe(true)
})

it('moves a nominal offset with the point but keeps a deliberate one', () => {
  expect(followOffset({ lon: -76.5, standard_offset_minutes: -300 }, 2)).toEqual({
    lon: 2,
    standard_offset_minutes: 0,
  })
  expect(
    followOffset({ lon: -76.5, standard_offset_minutes: -240 }, 2).standard_offset_minutes,
  ).toBe(-240)
})

it('gives newly drawn points longitude-based standard time instead of UTC', () => {
  expect(
    geometry('points', [
      [-76.5, 42.4],
      [139.7, 35.7],
    ]),
  ).toEqual([
    { lat: 42.4, lon: -76.5, standard_offset_minutes: -300 },
    { lat: 35.7, lon: 139.7, standard_offset_minutes: 540 },
  ])
})

import { it, expect } from 'vitest'
import { geometry } from './selection'
it('requires enough vertices and closes polygon rings', () => {
  expect(() =>
    geometry('polygon', [
      [1, 2],
      [2, 3],
    ]),
  ).toThrow()
  expect(
    geometry('polygon', [
      [1, 2],
      [2, 3],
      [3, 2],
    ]),
  ).toEqual({
    type: 'Polygon',
    coordinates: [
      [
        [1, 2],
        [2, 3],
        [3, 2],
        [1, 2],
      ],
    ],
  })
})
it('normalizes a box and bounds point lists', () => {
  expect(
    geometry('bbox', [
      [3, 4],
      [1, 2],
    ]),
  ).toEqual({ west: 1, south: 2, east: 3, north: 4 })
  expect(() => geometry('points', [])).toThrow()
})

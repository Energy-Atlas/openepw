import { it, expect } from 'vitest'
import { validateDraft } from './input'
it('rejects malformed expert JSON before it can break the UI', () => {
  for (const value of [
    { locations: null },
    { locations: [null] },
    { locations: { lat: 0, lon: 0 }, years: '2024' },
    { locations: { west: 0, east: 2, south: 0, north: 'bad' } },
  ])
    expect(() => validateDraft(value)).toThrow()
  expect(() =>
    validateDraft({
      locations: {
        type: 'Polygon',
        coordinates: [
          [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 0],
          ],
        ],
      },
      years: [2024],
    }),
  ).not.toThrow()
})

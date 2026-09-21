import { expect, it } from 'vitest'
import { APPEARANCES } from '../../shell/appearances'
import { coverageBeforeIds, datasetColor } from './datasetColor'

it('gives a dataset the same palette color everywhere, independent of selection order', () => {
  const color = datasetColor('openmeteo', 'era5', APPEARANCES.light)
  expect(APPEARANCES.light.data.categorical).toContain(color)
  expect(datasetColor('openmeteo', 'era5', APPEARANCES.light)).toBe(color)
})

it('inserts each coverage overlay beneath the one listed above it', () => {
  expect(
    coverageBeforeIds([
      { id: 'top', kind: 'vector' },
      { id: 'middle', kind: 'raster' },
      { id: 'bottom', kind: 'vector' },
    ]),
  ).toEqual({
    top: undefined,
    middle: 'coverage-fill-top',
    bottom: 'coverage-raster-middle',
  })
})

import { expect, it } from 'vitest'
import { datasetFacts } from './DownloadPanel'

const source = {
  provider: 'openmeteo',
  dataset: 'era5',
  access_path: 'public API',
  provisional: false,
  citation: 'Hersbach et al. (2020)',
  license: 'CC-BY-4.0',
}

it('summarizes years, interval, resolution, limitations and attribution for a dataset row', () => {
  const facts = datasetFacts(
    [
      {
        source,
        available_years: [2023, 2024],
        interval_minutes: 60,
        warnings: ['Gaps near coasts'],
      },
      { source, available_years: [2021], interval_minutes: 60, warnings: ['Gaps near coasts'] },
    ] as any,
    [
      {
        provider: 'openmeteo',
        dataset: 'era5',
        resolution_km: 31,
        attribution: 'Copernicus Climate Change Service',
        limitations: ['Reanalysis, not station observations'],
      },
      { provider: 'other', dataset: 'x', attribution: 'Unrelated', limitations: ['Ignore'] },
    ] as any,
  )
  expect(facts).toMatchObject({
    years: '2021–2024',
    interval: 'Hourly',
    resolution: '~31 km',
    access: 'public API',
    provisional: false,
  })
  expect(facts.limitations).toEqual(['Gaps near coasts', 'Reanalysis, not station observations'])
  expect(facts.attribution).toEqual([
    'Hersbach et al. (2020)',
    'CC-BY-4.0',
    'Copernicus Climate Change Service',
  ])
})

it('omits facts discovery did not report', () => {
  const facts = datasetFacts([{ source: { provider: 'p', dataset: 'd' } }] as any, [])
  expect(facts).toMatchObject({ years: null, interval: null, resolution: null, access: null })
  expect(facts.limitations).toEqual([])
})

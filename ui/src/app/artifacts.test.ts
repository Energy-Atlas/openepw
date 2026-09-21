import { expect, it } from 'vitest'
import { preferredWeatherArtifact, rankWeatherArtifacts } from './artifacts'

const om = { provider: 'openmeteo', dataset: 'era5', product_id: null }
const cds = { provider: 'cds', dataset: 'single-levels', product_id: null }
const candidate = (id: string, location: string, selection: typeof om) =>
  ({
    id,
    location_id: location,
    source: { provider: selection.provider, dataset: selection.dataset },
    product_id: null,
  }) as any
const output = (name: string, location: string, selection: typeof om) => ({
  name,
  requested_location_id: location,
  dataset_selection: selection,
  task_ids: [],
})
const epw = (name: string) => ({ id: name, path: `bundle/${name}`, role: 'weather' }) as any

// Point A ranks Open-Meteo first; point B ranks CDS first.
const state = {
  selectedDatasets: [om, cds],
  selectedLocationId: null as string | null,
  discovery: {
    candidates: [
      candidate('a-om', 'A', om),
      candidate('a-cds', 'A', cds),
      candidate('b-om', 'B', om),
      candidate('b-cds', 'B', cds),
    ],
    ranked_candidate_ids: { A: ['a-om', 'a-cds'], B: ['b-cds', 'b-om'] },
  },
  weatherPlan: {
    plan_hash: 'plan',
    outputs: [
      output('A-om.epw', 'A', om),
      output('A-cds.epw', 'A', cds),
      output('B-om.epw', 'B', om),
      output('B-cds.epw', 'B', cds),
    ],
  },
} as any
const job = (names: string[], patch: object = {}) =>
  ({
    id: 'j',
    kind: 'weather',
    plan_hash: 'plan',
    bundle: { weather: names.map(epw) },
    ...patch,
  }) as any
const bundle = ['B-om.epw', 'A-cds.epw', 'A-om.epw', 'B-cds.epw']

it('opens the backend-ranked EPW at the first planned point, not the first in the bundle', () => {
  expect(preferredWeatherArtifact(state, job(bundle))?.id).toBe('A-om.epw')
  expect(rankWeatherArtifacts(state, job(bundle)).map((item) => item.id)).toEqual([
    'A-om.epw',
    'A-cds.epw',
    'B-cds.epw',
    'B-om.epw',
  ])
})

it('ranks for the point selected on the map', () => {
  expect(preferredWeatherArtifact({ ...state, selectedLocationId: 'B' }, job(bundle))?.id).toBe(
    'B-cds.epw',
  )
})

it('falls back to the next-ranked dataset when the best one failed at that point', () => {
  expect(preferredWeatherArtifact(state, job(['B-om.epw', 'A-cds.epw']))?.id).toBe('A-cds.epw')
})

it('keeps bundle order for jobs from another plan and for projections', () => {
  expect(preferredWeatherArtifact(state, job(bundle, { plan_hash: 'older' }))?.id).toBe('B-om.epw')
  expect(preferredWeatherArtifact(state, job(bundle, { kind: 'future' }))?.id).toBe('B-om.epw')
  expect(preferredWeatherArtifact(state, job([]))).toBeUndefined()
})

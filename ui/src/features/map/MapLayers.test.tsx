import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { run } from '../../app/actions'
import { CoverageControl } from './CoverageControl'
import { PointGlyph } from './PointGlyph'
import { pointArtifacts, pointStatuses } from './MapView'
import { APPEARANCES } from '../../shell/appearances'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))
afterEach(cleanup)

it('labels documented and unknown coverage without implying availability', () => {
  const change = vi.fn()
  render(
    <CoverageControl
      layers={[
        {
          id: 'known',
          label: 'Known extent',
          provider: 'p',
          dataset: 'd',
          kind: 'vector',
          geometry: { type: 'Polygon', coordinates: [] },
          coverage_basis: 'documented',
          attribution: 'Provider documentation',
          observed_at: '2026-09-20T00:00:00Z',
          source_url: 'https://example.test',
        },
        {
          id: 'unknown',
          label: 'Unknown extent',
          provider: 'p',
          dataset: 'u',
          kind: 'unknown',
          coverage_basis: 'documented',
          attribution: 'Provider documentation',
          observed_at: '2026-09-20T00:00:00Z',
          source_url: 'https://example.test',
        },
      ]}
      selected={[]}
      onChange={change}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Coverage layers' }))
  expect(screen.getByText('Extents are not observed availability.')).toBeTruthy()
  expect(screen.getByText('No mapped extent; coverage is unknown.')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /Known extent/ }))
  expect(change).toHaveBeenCalledWith([{ id: 'known', opacity: 0.18 }])
})

it('renders unlimited status segments and opens an artifact picker', () => {
  const artifact = {
    id: 'a',
    role: 'weather',
    path: 'result.epw',
    media_type: 'application/vnd.energyplus.epw',
    bytes: 1,
    sha256: 'x',
  }
  render(
    <PointGlyph
      label="Sample 1"
      statuses={[
        { label: 'one', state: 'complete', color: '#100' },
        { label: 'two', state: 'selected', color: '#200' },
        { label: 'three', state: 'failed', color: '#300' },
        { label: 'four', state: 'gated', color: '#400' },
      ]}
      artifacts={[artifact]}
    />,
  )
  const point = screen.getByRole('button', { name: /Sample 1.*one: complete.*four: gated/ })
  expect(point.getAttribute('style')).toContain('conic-gradient')
  expect(point.getAttribute('style')).toContain('var(--tone-danger-text)')
  expect(point.getAttribute('style')).toContain('var(--color-text-muted)')
  fireEvent.click(point)
  fireEvent.click(screen.getByRole('button', { name: 'result.epw' }))
  expect(run).toHaveBeenCalledWith({ type: 'selectArtifact', artifact })
})

it('uses only the latest matching plan job for point status and artifacts', () => {
  const location = { id: 'point', lat: 42, lon: -76, standard_offset_minutes: 0 }
  const output = {
    requested_location_id: 'point',
    name: 'same.epw',
    dataset_selection: { provider: 'p', dataset: 'd', product_id: null },
  }
  const oldArtifact = {
    id: 'old',
    path: 'old/same.epw',
    media_type: 'application/vnd.energyplus.epw',
  }
  const state = {
    selectedDatasets: [{ provider: 'p', dataset: 'd', product_id: null }],
    discovery: {
      candidates: [
        {
          source: { provider: 'p', dataset: 'd' },
          product_id: null,
          location_id: 'point',
          requires_credentials: [],
        },
      ],
    },
    weatherPlan: { plan_hash: 'plan', outputs: [output] },
    downloadJobs: [
      { id: 'new', plan_hash: 'plan', state: 'failed', bundle: null },
      { id: 'old', plan_hash: 'plan', state: 'completed', bundle: { weather: [oldArtifact] } },
    ],
  } as any

  expect(pointStatuses(state, location as any, APPEARANCES.light)[0].state).toBe('failed')
  expect(pointArtifacts(state, location as any)).toEqual([])
})

it('marks stale discovery as unknown and unplanned points as incompatible', async () => {
  const { datasetColor } = await import('./datasetColor')
  const location = { id: 'point', lat: 42, lon: -76, standard_offset_minutes: 0 }
  const selection = { provider: 'p', dataset: 'd', product_id: null }
  const base = {
    requestVersion: 3,
    selectionVersion: 1,
    selectedDatasets: [selection],
    discovery: {
      candidates: [
        { source: { provider: 'p', dataset: 'd' }, product_id: null, location_id: 'point' },
      ],
    },
    downloadJobs: [],
  }
  const stale = { ...base, discoveryVersion: 2, weatherPlan: null } as any
  expect(pointStatuses(stale, location as any, APPEARANCES.light)[0].state).toBe('unknown')

  const unplanned = {
    ...base,
    discoveryVersion: 3,
    weatherPlan: { plan_hash: 'plan', outputs: [] },
    weatherPlanRequestVersion: 3,
    weatherPlanSelectionVersion: 1,
  } as any
  const [status] = pointStatuses(unplanned, location as any, APPEARANCES.light)
  expect(status.state).toBe('incompatible')
  expect(status.color).toBe(datasetColor('p', 'd', APPEARANCES.light))
})

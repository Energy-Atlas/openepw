import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { run } from '../../app/actions'
import { CoverageControl } from './CoverageControl'
import { PointGlyph } from './PointGlyph'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))
afterEach(cleanup)

it('labels documented and unknown coverage without implying availability', () => {
  const change = vi.fn()
  render(<CoverageControl layers={[{
    id: 'known', label: 'Known extent', provider: 'p', dataset: 'd', kind: 'vector',
    geometry: { type: 'Polygon', coordinates: [] }, coverage_basis: 'documented',
    attribution: 'Provider documentation', observed_at: '2026-09-20T00:00:00Z', source_url: 'https://example.test',
  }, {
    id: 'unknown', label: 'Unknown extent', provider: 'p', dataset: 'u', kind: 'unknown',
    coverage_basis: 'documented', attribution: 'Provider documentation',
    observed_at: '2026-09-20T00:00:00Z', source_url: 'https://example.test',
  }]} selected={[]} onChange={change} />)
  fireEvent.click(screen.getByRole('button', { name: 'Coverage layers' }))
  expect(screen.getByText('Extents are not observed availability.')).toBeTruthy()
  expect(screen.getByText('No mapped extent; coverage is unknown.')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /Known extent/ }))
  expect(change).toHaveBeenCalledWith([{ id: 'known', opacity: 0.32 }])
})

it('renders unlimited status segments and opens an artifact picker', () => {
  const artifact = { id: 'a', role: 'weather', path: 'result.epw', media_type: 'application/vnd.energyplus.epw', bytes: 1, sha256: 'x' }
  render(<PointGlyph label="Sample 1" statuses={[
    { label: 'one', state: 'complete', color: '#100' },
    { label: 'two', state: 'selected', color: '#200' },
    { label: 'three', state: 'failed', color: '#300' },
    { label: 'four', state: 'gated', color: '#400' },
  ]} artifacts={[artifact]} />)
  const point = screen.getByRole('button', { name: /Sample 1.*one: complete.*four: gated/ })
  expect(point.getAttribute('style')).toContain('conic-gradient')
  fireEvent.click(point)
  fireEvent.click(screen.getByRole('button', { name: 'result.epw' }))
  expect(run).toHaveBeenCalledWith({ type: 'selectArtifact', artifact })
})

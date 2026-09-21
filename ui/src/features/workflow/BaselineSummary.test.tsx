import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { useApp } from '../../app/store'
import { BaselineSummary } from './BaselineSummary'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('describes the active baseline location, period, calendar, origin and QC status', async () => {
  const baseline = {
    id: 'weather-artifact-1',
    role: 'weather',
    path: 'bundle/ithaca-era5.epw',
    media_type: 'application/vnd.energyplus.epw',
  } as any
  useApp.setState({
    weatherPlan: {
      outputs: [
        { name: 'ithaca-era5.epw', dataset_selection: { provider: 'openmeteo', dataset: 'era5' } },
      ],
    } as any,
    discovery: { candidates: [] } as any,
  })
  const visualization = vi.spyOn(api, 'visualization').mockResolvedValue({
    location: { lat: 42.44, lon: -76.5, name: 'Ithaca', standard_offset_minutes: -300 },
    calendar: 'gregorian',
    total_rows: 8784,
    timestamps: ['2024-01-01T00:00:00', '2024-12-31T23:00:00'],
    source_years: [2024, 2024],
    simulation_ready: false,
    synthetic_chronology: false,
  } as any)

  render(<BaselineSummary baseline={baseline} />)

  expect(await screen.findByText('Ithaca · 42.440, -76.500')).toBeTruthy()
  expect(visualization).toHaveBeenCalledWith('weather-artifact-1', ['dry_bulb'], expect.anything())
  expect(screen.getByText('2024-01-01 – 2024-12-31')).toBeTruthy()
  expect(screen.getByText('gregorian · 8,784 rows')).toBeTruthy()
  expect(screen.getByText(/openmeteo · era5/)).toBeTruthy()
  expect(screen.getByText('Annual QC passed; review before simulation')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Back to Download' })).toBeTruthy()
})

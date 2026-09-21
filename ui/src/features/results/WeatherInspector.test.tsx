import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { APPEARANCES } from '../../shell/appearances'
import { WeatherInspector } from './WeatherInspector'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))
vi.mock('./WeatherCharts', () => ({
  WeatherCharts: ({ heatVariable }: { heatVariable: string }) => <div>heatmap {heatVariable}</div>,
}))

const artifact = {
  id: 'a',
  role: 'weather',
  path: 'tmyx.epw',
  media_type: 'application/vnd.energyplus.epw',
  bytes: 1,
  sha256: 'x',
}
beforeEach(() =>
  useApp.setState({
    artifact,
    inspector: { open: true, manuallyCollapsed: false },
    visualization: {
      calendar: 'gregorian',
      location: { lat: 42, lon: -76, standard_offset_minutes: -300 },
      monthly: [
        {
          month: 1,
          year: 2024,
          expected: 744,
          source_years: [2008],
          values: { dry_bulb: { mean: 2, valid: 744 } },
        },
      ],
      series: {
        dry_bulb: [2, null],
        dni: [null, null],
        liquid_precipitation: [null, null],
      },
      timestamps: ['2024-01-01T01:00:00', '2024-01-01T02:00:00'],
      source_years: [2008, 2012],
      total_rows: 8784,
      units: { dry_bulb: 'degC', dni: 'Wh/m2', liquid_precipitation: 'mm' },
      simulation_ready: false,
      synthetic_chronology: true,
      warnings: ['Missing irradiance'],
    },
  }),
)
afterEach(cleanup)

it('reports leap/source provenance and explicit missing weather variables', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  expect(screen.getByText(/8,784 rows/)).toBeTruthy()
  expect(screen.getByText('Leap day retained')).toBeTruthy()
  expect(screen.getByText('Source years: 2008, 2012')).toBeTruthy()
  expect(screen.getByText('Precipitation unavailable')).toBeTruthy()
  expect(screen.getByText(/DNI unavailable/)).toBeTruthy()
  expect(screen.getByText('heatmap dry_bulb')).toBeTruthy()
  expect(
    (screen.getByRole('option', { name: 'Direct normal irradiance' }) as HTMLOptionElement)
      .disabled,
  ).toBe(true)
})

it('loads another full-artifact variable and remembers manual collapse', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  fireEvent.change(screen.getByLabelText('Hourly variable'), { target: { value: 'ghi' } })
  expect(run).toHaveBeenCalledWith({
    type: 'selectArtifact',
    artifact,
    variables: ['dry_bulb', 'liquid_precipitation', 'ghi'],
  })
  fireEvent.click(screen.getByRole('button', { name: 'Collapse weather inspector' }))
  expect(run).toHaveBeenCalledWith({ type: 'setInspector', open: false, manually: true })
})

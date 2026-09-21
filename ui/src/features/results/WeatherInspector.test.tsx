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

it('labels synthetic chronology, valid-hour coverage and offers the EPW download', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  expect(screen.getByText(/Synthetic chronology/)).toBeTruthy()
  expect(screen.getByText('Dry-bulb temperature: 1 of 8,784 hours valid')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Download tmyx.epw' })).toBeTruthy()
})

it('keeps a chosen heatmap variable and never requests a variable twice', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  fireEvent.change(screen.getByLabelText('Hourly variable'), { target: { value: 'dry_bulb' } })
  expect(run).toHaveBeenCalledWith({
    type: 'selectArtifact',
    artifact,
    variables: ['dry_bulb', 'liquid_precipitation'],
  })
  expect(useApp.getState().inspector.variable).toBe('dry_bulb')
})

it('switches to a paged table that loads rows and marks missing values', async () => {
  const { WeatherTable } = await import('./WeatherTable')
  const { rerender } = render(<WeatherTable artifactId="a" preview={null} busy={false} />)
  expect(run).toHaveBeenCalledWith({ type: 'previewPage', start: 0 })
  rerender(
    <WeatherTable
      artifactId="a"
      busy={false}
      preview={
        {
          start: 168,
          total_rows: 8784,
          units: { dry_bulb: 'degC', dni: 'Wh/m2' },
          rows: [
            {
              timestamp: '2024-01-08T00:00:00',
              source_year: 2024,
              values: { dry_bulb: 1.25, dni: null },
            },
          ],
        } as any
      }
    />,
  )
  expect(screen.getByText('Rows 169–169 of 8,784')).toBeTruthy()
  expect(screen.getByText('1.3')).toBeTruthy()
  expect(screen.getByText('missing')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Previous week' }))
  expect(run).toHaveBeenCalledWith({ type: 'previewPage', start: 0 })
  fireEvent.click(screen.getByRole('button', { name: 'Next week' }))
  expect(run).toHaveBeenCalledWith({ type: 'previewPage', start: 336 })
})

it('offers charts and table views of the active artifact', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  const table = screen.getByRole('button', { name: 'Table' })
  expect(screen.getByRole('button', { name: 'Charts' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(table)
  expect(table.getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByText(/^heatmap /)).toBeNull()
})

it('states the file time zone and flags one that contradicts the longitude', () => {
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  expect(screen.getByText('Hours: local standard time UTC−5')).toBeTruthy()
  expect(screen.queryByText(/File time zone differs/)).toBeNull()
  cleanup()
  const visualization = useApp.getState().visualization!
  useApp.setState({
    visualization: {
      ...visualization,
      location: { ...visualization.location, standard_offset_minutes: 0 },
    },
  })
  render(<WeatherInspector appearance={APPEARANCES.light} />)
  expect(screen.getByText('Hours: local standard time UTC')).toBeTruthy()
  expect(screen.getByText(/File time zone differs from this longitude's UTC−5/)).toBeTruthy()
})

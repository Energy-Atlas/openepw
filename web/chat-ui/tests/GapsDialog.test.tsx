import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { GapsDialog, type GapRow } from '../src/GapsDialog'
import { FIXTURES, fakeApi, messageField } from './agentFixtures'

afterEach(() => { cleanup(); sessionStorage.clear() })

const row = (id: string, label: string, selected: string): GapRow => ({
  id, number: 1, label, source: 'NOAA ISD station observations', places: 2, selected,
  options: [
    { id: 'source:openmeteo:era5', label: 'Fill from Open-Meteo ERA5', detail: 'Whole variables', recommended: true, places: 2 },
    { id: 'station_reports', label: "Use the station's own pressure reports", places: 1 },
    { id: 'leave_missing', label: 'Leave missing', places: 2 },
  ],
})

describe('data gaps dialog', () => {
  it('selects the recommended option per gap and sends the choice for each', () => {
    const onConfirm = vi.fn()
    render(<GapsDialog rows={[row('solar', 'Solar radiation (GHI, DNI, DHI)', 'source:openmeteo:era5'),
      row('pressure', 'Station pressure', 'station_reports')]} onConfirm={onConfirm} onType={vi.fn()} />)
    const radios = screen.getAllByRole('radio', { name: /Leave missing/ })
    expect(screen.getAllByRole('radio', { name: /Fill from Open-Meteo ERA5/ })[0]).toBeChecked()
    expect(screen.getAllByText('Recommended')).toHaveLength(2)
    expect(screen.getAllByText('at 1 of 2 places')).toHaveLength(2)    // possible only at some places
    fireEvent.click(radios[0])                                            // leave solar missing
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onConfirm).toHaveBeenCalledWith({ solar: 'leave_missing', pressure: 'station_reports' })
  })

  it('renders the real snapshot and answers with the choices', async () => {
    const api = fakeApi(FIXTURES.data_gaps)
    render(<App api={api} />)
    const dialog = await screen.findByRole('region', { name: 'Cover data gaps' })
    expect(within(dialog).getByText(/^Solar radiation/)).toBeInTheDocument()
    expect(within(dialog).getByText(/^Station pressure/)).toBeInTheDocument()
    // The question keeps its note, not the numbered rows the dialog already lists.
    const question = screen.getByLabelText('Current question')
    expect(question).toHaveTextContent('takes whole variables')
    expect(question).not.toHaveTextContent('1. NOAA ISD')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-2', expect.objectContaining({
      type: 'answer', answer: expect.objectContaining({ approve: true, value: { choices: {
        'noaa|ISD global-hourly|solar': 'source:openmeteo:era5',
        'noaa|ISD global-hourly|pressure': 'station_reports' } } }) })))
  })

  it('takes the choice in words instead', async () => {
    const api = fakeApi(FIXTURES.data_gaps)
    render(<App api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Other — type an answer' }))
    const field = await messageField()
    expect(field).toHaveAttribute('placeholder', 'e.g. "fill solar from Open-Meteo" or "leave pressure missing"')
    fireEvent.change(field, { target: { value: 'leave pressure missing' } })
    fireEvent.submit(field.closest('form')!)
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-2',
      { type: 'text', text: 'leave pressure missing' }))
  })
})

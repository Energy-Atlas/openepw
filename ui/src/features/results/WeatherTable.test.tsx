import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { useApp } from '../../app/store'
import { WeatherTable } from './WeatherTable'

function ActiveTable() {
  const preview = useApp((state) => state.preview)
  const busy = useApp((state) => state.busy)
  return <WeatherTable artifactId="weather-1" preview={preview} busy={busy} />
}

beforeEach(() => {
  useApp.setState({ artifact: { id: 'weather-1' } as any, preview: null, busy: false, error: '' })
  vi.restoreAllMocks()
})
afterEach(cleanup)

it('stops after a failed first page and retries only when requested', async () => {
  const preview = vi
    .spyOn(api, 'preview')
    .mockRejectedValueOnce(new Error('Preview unavailable'))
    .mockResolvedValueOnce({
      start: 0,
      total_rows: 1,
      units: {},
      rows: [{ timestamp: '2024-01-01T00:00:00', source_year: 2024, values: {} }],
    } as any)
  render(<ActiveTable />)
  await waitFor(() => expect(screen.getByText('Preview unavailable')).toBeTruthy())
  expect(preview).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Retry hourly rows' }))
  await waitFor(() => expect(screen.getByText('Rows 1–1 of 1')).toBeTruthy())
  expect(preview).toHaveBeenCalledTimes(2)
})

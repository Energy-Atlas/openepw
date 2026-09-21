import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { dispatch } from '../../app/actions'
import { useApp } from '../../app/store'
import { ExplorePanel } from './ExplorePanel'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('does not auto-retry after an explicit preview fails for the current query', async () => {
  vi.useFakeTimers()
  useApp.setState({
    requestVersion: 7,
    spatialPreviewVersion: null,
    spatialPreviewAttemptVersion: null,
    spatialPreview: null,
    busy: true,
  })
  const preview = vi
    .spyOn(api, 'spatialPreview')
    .mockRejectedValue(new Error('Preview unavailable'))
  render(<ExplorePanel />)

  act(() => useApp.setState({ busy: false }))
  await act(async () => {
    await expect(dispatch({ type: 'previewSpatial' })).rejects.toThrow('Preview unavailable')
  })
  await act(async () => vi.advanceTimersByTime(500))

  expect(preview).toHaveBeenCalledTimes(1)
  act(() => useApp.setState({ error: '' }))
  expect(screen.getByText(/Sample preview did not complete/)).toBeTruthy()
})

it('defers the automatic preview until another action is no longer busy', async () => {
  vi.useFakeTimers()
  useApp.setState({
    requestVersion: 8,
    spatialPreviewVersion: null,
    spatialPreviewAttemptVersion: null,
    spatialPreview: null,
    busy: true,
  })
  const preview = vi.spyOn(api, 'spatialPreview').mockResolvedValue({
    locations: [{ lat: 42.44, lon: -76.5, standard_offset_minutes: 0, id: 'point' }],
    total_count: 1,
    returned_count: 1,
    planned_output_count: 1,
    execution_limit: 1000,
    executable: true,
    truncated: false,
    issues: [],
  })
  render(<ExplorePanel />)

  await act(async () => vi.advanceTimersByTime(500))
  expect(preview).not.toHaveBeenCalled()
  act(() => useApp.setState({ busy: false }))
  await act(async () => vi.advanceTimersByTime(500))

  expect(preview).toHaveBeenCalledTimes(1)
  expect(useApp.getState().spatialPreviewVersion).toBe(8)
})

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

it('sends one preview per query version, even while a slow preview is in flight', async () => {
  vi.useFakeTimers()
  useApp.setState({
    requestVersion: 9,
    spatialPreviewVersion: null,
    spatialPreviewAttemptVersion: null,
    spatialPreview: null,
    busy: false,
  })
  let finish!: () => void
  const result = {
    locations: [{ lat: 42.44, lon: -76.5, standard_offset_minutes: 0, id: 'point' }],
    total_count: 1,
    returned_count: 1,
    planned_output_count: 1,
    execution_limit: 1000,
    executable: true,
    truncated: false,
    issues: [],
  }
  const preview = vi
    .spyOn(api, 'spatialPreview')
    .mockImplementationOnce(() => new Promise((resolve) => (finish = () => resolve(result))))
    .mockResolvedValue(result)
  render(<ExplorePanel />)

  await act(async () => vi.advanceTimersByTime(6000))
  expect(preview).toHaveBeenCalledTimes(1)
  await act(async () => finish())
  await act(async () => vi.advanceTimersByTime(6000))
  expect(preview).toHaveBeenCalledTimes(1)
  expect(useApp.getState().spatialPreviewVersion).toBe(9)

  act(() => useApp.setState({ requestVersion: 10 }))
  await act(async () => vi.advanceTimersByTime(6000))
  expect(preview).toHaveBeenCalledTimes(2)
  expect(useApp.getState().spatialPreviewVersion).toBe(10)
})

it('warns when a point offset contradicts its longitude and fixes it in one step', async () => {
  const { fireEvent, screen } = await import('@testing-library/react')
  useApp.setState({
    busy: false,
    pendingConfirmation: null,
    baselineOrigin: null,
    discoveryVersion: null,
    weatherPlan: null,
    downloadJobs: [],
    spatialPreviewVersion: 1,
    requestVersion: 1,
    draft: {
      ...useApp.getState().draft,
      locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 },
    },
  })
  render(<ExplorePanel />)
  expect(screen.getByText(/is far from this longitude/).textContent).toContain('UTC−5')
  fireEvent.click(screen.getByRole('button', { name: 'Use UTC−5' }))
  expect((useApp.getState().draft.locations as any).standard_offset_minutes).toBe(-300)

  cleanup()
  useApp.setState({
    draft: {
      ...useApp.getState().draft,
      locations: { west: -77, south: 42, east: -76, north: 43 },
    },
  })
  render(<ExplorePanel />)
  const policy = screen.getByLabelText(/Standard time for sampled points/) as HTMLSelectElement
  expect(policy.value).toBe('longitude')
  fireEvent.change(policy, { target: { value: 'utc' } })
  expect(useApp.getState().draft.sampling?.standard_offset).toBe('utc')
})

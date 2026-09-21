import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { useApp } from '../../app/store'
import { HistoryDrawer, useJobMonitor } from './HistoryDrawer'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function Harness() {
  useJobMonitor()
  return <HistoryDrawer open onClose={() => {}} />
}

it('advances a partially completed Download to Project and keeps its failures explicit', async () => {
  vi.useFakeTimers()
  const running = { id: 'job-partial', state: 'running', completed: 0, failed: 0, total: 3 }
  const partial = {
    ...running,
    state: 'partially_completed',
    completed: 2,
    failed: 1,
    errors: [{ code: 'SOURCE_UNAVAILABLE', message: 'Synthetic alternate source is unavailable' }],
    bundle: {
      weather: [{ id: 'made', path: 'made.epw', role: 'weather' }],
      ...Object.fromEntries(
        ['manifest', 'qc', 'request', 'plan'].map((role) => [
          role,
          { id: role, path: `${role}.json`, role },
        ]),
      ),
    },
  }
  useApp.setState({
    stage: 'download',
    job: running as any,
    jobs: [],
    downloadJobs: [running as any],
    projectJobs: [],
  })
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [partial], next_cursor: null } as any)
  const poll = vi.spyOn(api, 'job').mockResolvedValue(partial as any)
  render(<Harness />)

  await act(async () => vi.advanceTimersByTime(500))
  expect(poll).toHaveBeenCalledTimes(1)
  expect(useApp.getState().stage).toBe('project')
  expect(useApp.getState().downloadJobs[0].state).toBe('partially_completed')
  expect(screen.getByText('partially completed')).toBeTruthy()
  expect(screen.getByText('2 complete, 1 failed')).toBeTruthy()
  expect(screen.getByText(/SOURCE_UNAVAILABLE/)).toBeTruthy()
  await act(async () => vi.advanceTimersByTime(5000))
  expect(poll).toHaveBeenCalledTimes(1)
})

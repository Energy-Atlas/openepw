import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { HistoryDrawer, useJobMonitor, useJobReconcile } from './HistoryDrawer'

vi.mock('../../app/actions', () => ({ run: vi.fn() }))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.mocked(run).mockClear()
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

it('selects a completed job artifact after a concurrent action finishes', async () => {
  vi.useFakeTimers()
  const weather = { id: 'made', path: 'made.epw', role: 'weather' }
  const running = { id: 'job-busy', kind: 'weather', state: 'running', completed: 0, failed: 0 }
  const done = { ...running, state: 'completed', completed: 1, bundle: { weather: [weather] } }
  useApp.setState({
    stage: 'download',
    job: running as any,
    jobs: [],
    downloadJobs: [running as any],
    projectJobs: [],
    artifact: null,
    busy: true,
  })
  vi.spyOn(api, 'job').mockResolvedValue(done as any)
  function Monitor() {
    useJobMonitor()
    return null
  }
  render(<Monitor />)

  await act(async () => vi.advanceTimersByTime(500))
  expect(useApp.getState().stage).toBe('project')
  expect(run).not.toHaveBeenCalled()

  act(() => useApp.setState({ busy: false }))
  expect(run).toHaveBeenCalledWith({ type: 'selectArtifact', artifact: weather })
})

it('reconciles History after reload and resumes an unfinished job', async () => {
  const earlier = { id: 'earlier', path: 'earlier.epw', role: 'weather' }
  const finished = {
    id: 'done',
    kind: 'weather',
    state: 'completed',
    bundle: { weather: [{ ...earlier, media_type: 'application/vnd.energyplus.epw' }] },
  }
  const unfinished = { id: 'running', kind: 'weather', state: 'running' }
  useApp.setState({
    stage: 'project',
    job: null,
    jobs: [],
    downloadJobs: [],
    projectJobs: [],
    importedArtifacts: [],
    discovery: null,
  })
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [unfinished, finished] } as any)
  function Reconcile() {
    useJobReconcile()
    return null
  }
  render(<Reconcile />)

  await vi.waitFor(() => expect(useApp.getState().job?.id).toBe('running'))
  const state = useApp.getState()
  expect(state.downloadJobs.map((job) => job.id)).toEqual(['running'])
  expect(state.jobs.map((job) => job.id)).toEqual(['running', 'done'])
  expect(state.stage).toBe('project')
})

it('returns a restored locked stage to Explore when no baseline exists', async () => {
  useApp.setState({
    stage: 'project',
    job: null,
    jobs: [],
    downloadJobs: [],
    projectJobs: [],
    importedArtifacts: [],
    discovery: null,
  })
  vi.spyOn(api, 'jobs').mockRejectedValue(new Error('offline'))
  function Reconcile() {
    useJobReconcile()
    return null
  }
  render(<Reconcile />)

  await vi.waitFor(() => expect(useApp.getState().stage).toBe('explore'))
})

it('opens the backend-ranked EPW when a Download finishes', async () => {
  vi.useFakeTimers()
  const selection = { provider: 'p', dataset: 'good', product_id: null }
  const worse = { provider: 'p', dataset: 'worse', product_id: null }
  const running = {
    id: 'ranked',
    kind: 'weather',
    plan_hash: 'plan',
    state: 'running',
    total: 2,
    completed: 0,
    failed: 0,
  }
  const done = {
    ...running,
    state: 'completed',
    completed: 2,
    bundle: {
      weather: [
        { id: 'worse', path: 'x/worse.epw' },
        { id: 'good', path: 'x/good.epw' },
      ],
    },
  }
  useApp.setState({
    stage: 'download',
    busy: false,
    artifact: null,
    job: running as any,
    jobs: [],
    downloadJobs: [running as any],
    projectJobs: [],
    selectedDatasets: [worse, selection],
    selectedLocationId: null,
    discovery: {
      candidates: [
        {
          id: 'c-good',
          location_id: 'L',
          source: { provider: 'p', dataset: 'good' },
          product_id: null,
        },
        {
          id: 'c-worse',
          location_id: 'L',
          source: { provider: 'p', dataset: 'worse' },
          product_id: null,
        },
      ],
      ranked_candidate_ids: { L: ['c-good', 'c-worse'] },
    } as any,
    weatherPlan: {
      plan_hash: 'plan',
      outputs: [
        { name: 'worse.epw', requested_location_id: 'L', dataset_selection: worse, task_ids: [] },
        {
          name: 'good.epw',
          requested_location_id: 'L',
          dataset_selection: selection,
          task_ids: [],
        },
      ],
    } as any,
  })
  vi.spyOn(api, 'job').mockResolvedValue(done as any)
  function Monitor() {
    useJobMonitor()
    return null
  }
  render(<Monitor />)
  await act(async () => vi.advanceTimersByTime(500))
  expect(run).toHaveBeenCalledWith({
    type: 'selectArtifact',
    artifact: { id: 'good', path: 'x/good.epw' },
  })
})

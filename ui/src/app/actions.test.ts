import { rememberIntent } from './intent'
import { it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api/client'
import { ACTION_REGISTRY, confirmPendingAction, dispatch } from './actions'
import { useApp } from './store'
import { deriveWorkflow } from './workflow'
beforeEach(() => {
  useApp.setState({
    stage: 'explore',
    version: 0,
    requestVersion: 0,
    selectionVersion: 0,
    futureVersion: 0,
    discovery: null,
    discoveryVersion: null,
    weatherPlan: null,
    weatherPlanRequestVersion: null,
    weatherPlanSelectionVersion: null,
    futurePlan: null,
    futurePlanVersion: null,
    futurePlanBaselineId: null,
    plan: null,
    selectedDatasets: [],
    downloadJobs: [],
    projectJobs: [],
    importedArtifacts: [],
    activeWeatherArtifact: null,
    artifact: null,
    preview: null,
    visualization: null,
    detail: null,
    busy: false,
    jobs: [],
    job: null,
    submitKeys: { weather: null, future: null },
    submitted: { weather: false, future: false },
    pendingConfirmation: null,
  })
  vi.restoreAllMocks()
  localStorage.clear()
})
it('ignores a discovery result after request edits', async () => {
  let resolve!: (v: any) => void
  vi.spyOn(api, 'spatialPreview').mockResolvedValue({ executable: true } as any)
  vi.spyOn(api, 'discover').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'discover' })
  useApp.getState().edit({ years: [2023] })
  resolve({ locations: [], candidates: [], issues: [] })
  await pending
  expect(useApp.getState().discovery).toBeNull()
})
it('marks a reviewed plan stale on draft edits while preserving immutable state', () => {
  const plan = { kind: 'weather', plan_hash: 'old' } as any
  useApp.setState({
    plan,
    weatherPlan: plan,
    weatherPlanRequestVersion: 0,
    weatherPlanSelectionVersion: 0,
  })
  useApp.getState().edit({ years: [2022] })
  expect(useApp.getState().weatherPlan).toBe(plan)
  expect(deriveWorkflow(useApp.getState()).stages.download.stale).toBe(true)
})

it('reuses a submit idempotency key after a lost response', async () => {
  const plan = { kind: 'weather', plan_hash: 'plan' } as any
  useApp.setState({ plan, submitKeys: { weather: 'same-intent', future: null } })
  const submit = vi
    .spyOn(api, 'submit')
    .mockRejectedValueOnce(new Error('connection lost'))
    .mockResolvedValueOnce({ id: 'job', state: 'queued' } as any)
  await expect(dispatch({ type: 'submitPlan' })).rejects.toThrow()
  await dispatch({ type: 'submitPlan' })
  expect(submit.mock.calls.map((c) => c[1])).toEqual(['same-intent', 'same-intent'])
})
it('keeps an edited request unsubmitted after an older submission returns', async () => {
  useApp.setState({
    plan: { kind: 'weather' } as any,
    submitKeys: { weather: 'old', future: null },
  })
  let resolve!: (v: any) => void
  vi.spyOn(api, 'submit').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'submitPlan' })
  useApp.getState().edit({ years: [2021] })
  resolve({ id: 'job', state: 'queued' })
  await pending
  expect(useApp.getState().submitted.weather).toBe(false)
})
it('selecting another job clears the previous artifact preview', async () => {
  useApp.setState({ artifact: { id: 'old' } as any, preview: { total_rows: 24 } as any })
  vi.spyOn(api, 'job').mockResolvedValue({ id: 'new', state: 'completed' } as any)
  await dispatch({ type: 'selectJob', id: 'new' })
  expect(useApp.getState().artifact).toBeNull()
  expect(useApp.getState().preview).toBeNull()
})

it('submitting a new job clears old inspection state', async () => {
  useApp.setState({
    plan: { kind: 'weather' } as any,
    artifact: { id: 'old' } as any,
    preview: {} as any,
    detail: { old: true },
  })
  vi.spyOn(api, 'submit').mockResolvedValue({ id: 'new', state: 'queued' } as any)
  await dispatch({ type: 'submitPlan' })
  expect(useApp.getState().artifact).toBeNull()
  expect(useApp.getState().preview).toBeNull()
  expect(useApp.getState().detail).toBeNull()
})
it('stopping an upload suppresses a late completion', async () => {
  let resolve!: (v: any) => void
  const baseline = useApp.getState().future.baseline
  vi.spyOn(api, 'upload').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'uploadBaseline', file: new File(['data'], 'test.epw') })
  await dispatch({ type: 'cancelActive' })
  resolve({ id: 'late' })
  await expect(pending).rejects.toThrow()
  expect(useApp.getState().future.baseline).toBe(baseline)
  expect(useApp.getState().busy).toBe(false)
})

it('replanning after reload reuses persisted submission intent', async () => {
  rememberIntent('same-plan', 'before-reload')
  vi.spyOn(api, 'plan').mockResolvedValue({ kind: 'weather', plan_hash: 'same-plan' } as any)
  await dispatch({ type: 'planWeather' })
  expect(useApp.getState().submitKeys.weather).toBe('before-reload')
  expect(useApp.getState().submitted.weather).toBe(false)
})

it('explains a missing future baseline before making an invalid request', async () => {
  useApp.getState().editFuture({ baseline: '' })
  const plan = vi.spyOn(api, 'plan')
  await expect(dispatch({ type: 'planFuture' })).rejects.toThrow('Upload a baseline EPW')
  expect(plan).not.toHaveBeenCalled()
})

it('runs Explore through authoritative sampling and discovery before advancing', async () => {
  useApp.setState({
    spatialPreview: { executable: true } as any,
    spatialPreviewVersion: useApp.getState().requestVersion,
  })
  vi.spyOn(api, 'spatialPreview').mockResolvedValue({ executable: true } as any)
  vi.spyOn(api, 'discover').mockResolvedValue({
    candidates: [
      {
        id: 'recommended',
        source: { provider: 'era5', dataset: 'era5' },
        product_id: null,
      },
    ],
    selected_candidate_ids: ['recommended'],
  } as any)

  await dispatch({ type: 'runCurrentStage' })

  expect(useApp.getState().stage).toBe('download')
  expect(useApp.getState().selectedDatasets).toEqual([
    { provider: 'era5', dataset: 'era5', product_id: null },
  ])
  expect(useApp.getState().discoveryVersion).toBe(useApp.getState().requestVersion)
})

it('loads full visualization and opens the inspector when weather is selected', async () => {
  const visualization = { total_rows: 8760, series: {} } as any
  vi.spyOn(api, 'visualization').mockResolvedValue(visualization)
  const artifact = {
    id: 'weather',
    role: 'weather',
    media_type: 'application/vnd.energyplus.epw',
  } as any
  useApp.setState({
    downloadJobs: [{ id: 'download', kind: 'weather', bundle: { weather: [artifact] } } as any],
  })

  await dispatch({ type: 'selectArtifact', artifact })

  expect(useApp.getState().visualization).toBe(visualization)
  expect(useApp.getState().inspector.open).toBe(true)
  expect(useApp.getState().activeWeatherArtifact).toBe(artifact)
})

it('inspects a projected EPW without replacing the Project baseline', async () => {
  vi.spyOn(api, 'visualization').mockResolvedValue({ total_rows: 8760, series: {} } as any)
  const epw = 'application/vnd.energyplus.epw'
  const baseline = { id: 'baseline', role: 'baseline', media_type: epw } as any
  const projected = { id: 'projected', role: 'weather', media_type: epw } as any
  useApp.setState({
    stage: 'project',
    importedArtifacts: [baseline],
    activeWeatherArtifact: baseline,
    baselineOrigin: 'upload',
    future: { ...useApp.getState().future, baseline: 'baseline' },
    projectJobs: [
      { id: 'future', kind: 'future', state: 'completed', bundle: { weather: [projected] } } as any,
    ],
  })
  const futureVersion = useApp.getState().futureVersion

  await dispatch({ type: 'selectArtifact', artifact: projected })

  const state = useApp.getState()
  expect(state.artifact).toBe(projected)
  expect(state.inspector.open).toBe(true)
  expect(state.activeWeatherArtifact).toBe(baseline)
  expect(state.future.baseline).toBe('baseline')
  expect(state.futureVersion).toBe(futureVersion)
  expect(deriveWorkflow(state).activeBaseline).toBe(baseline)
})

it('accepts a weather EPW from an earlier session as a Project baseline', async () => {
  vi.spyOn(api, 'visualization').mockResolvedValue({ total_rows: 8760, series: {} } as any)
  const earlier = {
    id: 'earlier',
    role: 'weather',
    media_type: 'application/vnd.energyplus.epw',
  } as any
  useApp.setState({
    jobs: [
      { id: 'old', kind: 'weather', state: 'completed', bundle: { weather: [earlier] } } as any,
    ],
  })
  expect(deriveWorkflow(useApp.getState()).stages.project.unlocked).toBe(true)

  await dispatch({ type: 'selectArtifact', artifact: earlier })

  expect(useApp.getState().future.baseline).toBe('earlier')
  expect(deriveWorkflow(useApp.getState()).activeBaseline).toBe(earlier)
})

it('keeps Download and Project submission keys independent', async () => {
  const weather = { kind: 'weather', plan_hash: 'weather-plan' } as any
  const future = { kind: 'future', plan_hash: 'future-plan' } as any
  useApp.setState({ submitKeys: { weather: 'weather-key', future: 'future-key' } })
  const submit = vi
    .spyOn(api, 'submit')
    .mockResolvedValueOnce({ id: 'projection', state: 'queued' } as any)
    .mockResolvedValueOnce({ id: 'download', state: 'queued' } as any)

  useApp.setState({ plan: future })
  await dispatch({ type: 'submitPlan' })
  useApp.setState({ plan: weather })
  await dispatch({ type: 'submitPlan' })

  expect(submit.mock.calls.map((call) => call[1])).toEqual(['future-key', 'weather-key'])
  expect(useApp.getState().submitted).toEqual({ weather: true, future: true })
  expect(useApp.getState().downloadJobs.map((job) => job.id)).toEqual(['download'])
  expect(useApp.getState().projectJobs.map((job) => job.id)).toEqual(['projection'])
})

it('publishes confirmation metadata for shared job and invalidation actions', () => {
  expect(ACTION_REGISTRY.submitPlan.confirmation).toBe('job')
  expect(ACTION_REGISTRY.editQuery.confirmation).toBe('downstream-invalidation')
  expect(ACTION_REGISTRY.selectArtifact.confirmation).toBe('none')
})

it('submits only a current Download plan after explicit confirmation', async () => {
  const plan = { kind: 'weather', plan_hash: 'weather-plan' } as any
  useApp.setState({
    stage: 'download',
    discovery: { candidates: [{ id: 'candidate' }] } as any,
    discoveryVersion: 0,
    selectedDatasets: [{ provider: 'era5', dataset: 'era5' }],
    weatherPlan: plan,
    weatherPlanRequestVersion: 0,
    weatherPlanSelectionVersion: 0,
  })
  const submit = vi.spyOn(api, 'submit').mockResolvedValue({ id: 'job', state: 'queued' } as any)

  await expect(dispatch({ type: 'runCurrentStage' })).rejects.toThrow(/Confirm/)
  await dispatch({ type: 'runCurrentStage', confirmed: true })

  expect(submit).toHaveBeenCalledWith(plan, expect.any(String), expect.any(AbortSignal))
  expect(useApp.getState().downloadJobs[0].id).toBe('job')
})

it('registers a parsed upload as eligible but not implicitly simulation-ready', async () => {
  const upload = {
    id: 'upload',
    role: 'baseline',
    media_type: 'application/vnd.energyplus.epw',
    path: 'baseline.epw',
  } as any
  vi.spyOn(api, 'upload').mockResolvedValue(upload)
  vi.spyOn(api, 'visualization').mockResolvedValue({ simulation_ready: false } as any)

  await dispatch({ type: 'uploadBaseline', file: new File(['epw'], 'baseline.epw') })

  expect(useApp.getState().importedArtifacts).toContain(upload)
  expect(useApp.getState().activeWeatherArtifact).toBe(upload)
  expect(useApp.getState().future.baseline).toBe('upload')
  expect(useApp.getState().visualization?.simulation_ready).toBe(false)
})

it('creates a new immutable Project job for an intentional rerun', async () => {
  const plan = { kind: 'future', plan_hash: 'future-plan' } as any
  const baseline = { id: 'baseline', media_type: 'application/vnd.energyplus.epw' } as any
  useApp.setState({
    stage: 'project',
    plan,
    futurePlan: plan,
    futurePlanVersion: 0,
    futurePlanBaselineId: 'baseline',
    activeWeatherArtifact: baseline,
    importedArtifacts: [baseline],
    future: { ...useApp.getState().future, baseline: 'baseline' },
  })
  vi.spyOn(api, 'submit')
    .mockResolvedValueOnce({ id: 'first', state: 'queued' } as any)
    .mockResolvedValueOnce({ id: 'second', state: 'queued' } as any)

  await dispatch({ type: 'submitPlan' })
  await expect(dispatch({ type: 'rerunPlan' })).rejects.toThrow(/Confirm/)
  await dispatch({ type: 'rerunPlan', confirmed: true })

  expect(useApp.getState().projectJobs.map((job) => job.id)).toEqual(['second', 'first'])
})

it('confirms an upstream edit before invalidating a current reviewed plan', async () => {
  const plan = { kind: 'weather', plan_hash: 'current' } as any
  useApp.setState({
    weatherPlan: plan,
    weatherPlanRequestVersion: 0,
    weatherPlanSelectionVersion: 0,
  })

  await dispatch({ type: 'editQuery', patch: { years: [2022] } })

  expect(useApp.getState().requestVersion).toBe(0)
  expect(useApp.getState().pendingConfirmation?.title).toMatch(/upstream/i)
  await confirmPendingAction()
  expect(useApp.getState().requestVersion).toBe(1)
  expect(useApp.getState().draft.years).toEqual([2022])
})

import { api, type Artifact, type FutureRequest, type WeatherRequest } from '../api/client'
import { rememberedIntent, rememberIntent } from './intent'
import { useApp, validAppearance, type State } from './store'
import type { AppearancePreference } from '../shell/appearances'
import { clampPanelSize, type ResizablePanel } from '../shell/panels'
import { canNavigate, deriveWorkflow, type DatasetSelection, type Stage } from './workflow'

export const ACTION_REGISTRY = {
  editQuery: { confirmation: 'downstream-invalidation', reversible: true },
  editFuture: { confirmation: 'downstream-invalidation', reversible: true },
  selectDatasets: { confirmation: 'downstream-invalidation', reversible: true },
  navigate: { confirmation: 'none', reversible: true },
  previewSpatial: { confirmation: 'none', reversible: true },
  discover: { confirmation: 'none', reversible: false },
  planWeather: { confirmation: 'none', reversible: false },
  planFuture: { confirmation: 'none', reversible: false },
  runCurrentStage: { confirmation: 'stage-dependent', reversible: false },
  submitPlan: { confirmation: 'job', reversible: false },
  rerunPlan: { confirmation: 'job', reversible: false },
  retryFailed: { confirmation: 'job', reversible: false },
  selectJob: { confirmation: 'none', reversible: true },
  cancelJob: { confirmation: 'job', reversible: false },
  cancelActive: { confirmation: 'none', reversible: true },
  selectArtifact: { confirmation: 'none', reversible: true },
  uploadBaseline: { confirmation: 'none', reversible: false },
  uploadSignals: { confirmation: 'none', reversible: false },
  previewPage: { confirmation: 'none', reversible: true },
  loadCoverage: { confirmation: 'none', reversible: true },
  setCoverageSelection: { confirmation: 'none', reversible: true },
  setInspector: { confirmation: 'none', reversible: true },
  setAppearance: { confirmation: 'none', reversible: true },
  setPanelSize: { confirmation: 'none', reversible: true },
  selectLocation: { confirmation: 'none', reversible: true },
} as const

export type AppAction =
  | { type: 'editQuery'; patch: Partial<WeatherRequest>; confirmed?: boolean }
  | { type: 'editFuture'; patch: Partial<FutureRequest>; confirmed?: boolean }
  | { type: 'selectDatasets'; selections: DatasetSelection[]; confirmed?: boolean }
  | { type: 'navigate'; stage: Stage }
  | {
      type:
        | 'previewSpatial'
        | 'discover'
        | 'planWeather'
        | 'planFuture'
        | 'submitPlan'
        | 'cancelActive'
        | 'loadCoverage'
    }
  | { type: 'rerunPlan'; confirmed?: boolean }
  | { type: 'retryFailed'; id: string; confirmed?: boolean }
  | { type: 'runCurrentStage'; confirmed?: boolean }
  | { type: 'selectJob'; id: string }
  | { type: 'cancelJob'; id: string }
  | { type: 'selectArtifact'; artifact: Artifact; variables?: string[] }
  | { type: 'uploadBaseline' | 'uploadSignals'; file: File }
  | { type: 'previewPage'; start: number }
  | { type: 'setCoverageSelection'; ids: string[] }
  | { type: 'setInspector'; open: boolean; manually?: boolean }
  | { type: 'setAppearance'; appearance: AppearancePreference }
  | { type: 'setPanelSize'; panel: ResizablePanel; size: number }
  | { type: 'selectLocation'; id: string | null }

export type Action = AppAction
type InvalidatingAction = Extract<
  AppAction,
  { type: 'editQuery' | 'editFuture' | 'selectDatasets' }
>
const QUIET_ACTIONS = new Set<AppAction['type']>(['previewSpatial', 'loadCoverage', 'previewPage'])
let active: AbortController | null = null
let pendingInvalidation: InvalidatingAction | null = null

function isInvalidatingAction(action: AppAction): action is InvalidatingAction {
  return ['editQuery', 'editFuture', 'selectDatasets'].includes(action.type)
}

const terminalJobStates = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])

function completedFrom(jobs: State['downloadJobs'], plan: State['plan'], current: boolean) {
  return (
    current &&
    plan != null &&
    jobs.some((job) => terminalJobStates.has(job.state) && job.plan_hash === plan.plan_hash)
  )
}

// Only completed downstream work warrants confirmation; current discoveries and plans are
// derived, reversible state and refresh automatically after an edit.
function invalidatesCurrentWork(state: State, action: InvalidatingAction) {
  if (action.type === 'editFuture')
    return completedFrom(
      state.projectJobs,
      state.futurePlan,
      state.futurePlanVersion === state.futureVersion &&
        state.futurePlanBaselineId === state.future.baseline,
    )
  return (
    state.baselineOrigin === 'download' ||
    completedFrom(
      state.downloadJobs,
      state.weatherPlan,
      state.weatherPlanRequestVersion === state.requestVersion &&
        state.weatherPlanSelectionVersion === state.selectionVersion,
    )
  )
}

function queueInvalidation(action: InvalidatingAction) {
  pendingInvalidation = { ...action, confirmed: true }
  useApp.setState({
    pendingConfirmation: {
      title: 'Update upstream inputs?',
      description:
        'This keeps job history and artifacts, but marks the dependent reviewed plan and active results stale.',
    },
  })
}

export function dismissPendingAction() {
  pendingInvalidation = null
  useApp.setState({ pendingConfirmation: null })
}

export async function confirmPendingAction() {
  const action = pendingInvalidation
  pendingInvalidation = null
  useApp.setState({ pendingConfirmation: null })
  if (action) return dispatch(action)
}

// Explore is provider-free: dataset choices from an earlier discovery must not shrink the
// sampling limit. Download plans enforce the per-dataset output limit.
function exploreRequest(draft: WeatherRequest): WeatherRequest {
  return { ...draft, dataset_selections: [] }
}

function recommendedSelections(discovery: Awaited<ReturnType<typeof api.discover>>) {
  const selected = new Set(discovery.selected_candidate_ids)
  const identities = discovery.candidates
    .filter((candidate) => selected.has(candidate.id))
    .map((candidate) => ({
      provider: candidate.source.provider,
      dataset: candidate.source.dataset,
      product_id: candidate.product_id,
    }))
  return [
    ...new Map(identities.map((selection) => [JSON.stringify(selection), selection])).values(),
  ]
}

export async function dispatch(action: AppAction): Promise<unknown> {
  const state = useApp.getState()
  if (action.type === 'cancelActive') {
    active?.abort()
    state.log(
      'Client cancellation requested; server jobs continue. Refresh History to reconcile submissions.',
    )
    return
  }
  if (isInvalidatingAction(action) && !action.confirmed && invalidatesCurrentWork(state, action)) {
    queueInvalidation(action)
    return
  }
  if (action.type === 'editQuery') return state.edit(action.patch)
  if (action.type === 'editFuture') return state.editFuture(action.patch)
  if (action.type === 'selectDatasets') return state.selectDatasets(action.selections)
  if (action.type === 'setCoverageSelection')
    return useApp.setState({ selectedCoverageIds: action.ids })
  if (action.type === 'setInspector') return state.setInspectorOpen(action.open, action.manually)
  // Layout and appearance are synchronous and reversible, so they never wait on a request.
  if (action.type === 'setAppearance') {
    if (!validAppearance(action.appearance)) throw new Error('Unknown appearance.')
    return useApp.setState({ appearance: action.appearance })
  }
  if (action.type === 'selectLocation') return useApp.setState({ selectedLocationId: action.id })
  if (action.type === 'setPanelSize')
    return useApp.setState((current) => ({
      panelSizes: {
        ...current.panelSizes,
        [action.panel]: clampPanelSize(action.panel, action.size),
      },
    }))
  if (action.type === 'navigate') {
    const status = deriveWorkflow(state)
    if (!canNavigate(status, action.stage)) throw new Error(`${action.stage} is not unlocked yet.`)
    return state.setStage(action.stage)
  }
  if (action.type === 'runCurrentStage') {
    const status = deriveWorkflow(state)
    if (!status.run.enabled) throw new Error(status.run.reason ?? 'The current stage is not ready.')
    if (state.stage === 'explore') return dispatch({ type: 'discover' })
    if (!action.confirmed)
      throw new Error(
        state.stage === 'download'
          ? 'Confirm starting the weather download job.'
          : 'Confirm starting the projection job.',
      )
    useApp.setState({ plan: state.stage === 'download' ? state.weatherPlan : state.futurePlan })
    return dispatch({ type: 'submitPlan' })
  }
  if (action.type === 'rerunPlan') {
    const status = deriveWorkflow(state)
    const currentPlan = state.stage === 'download' ? state.weatherPlan : state.futurePlan
    if (!status.run.enabled || !currentPlan)
      throw new Error(status.run.reason ?? 'Review a current plan before rerunning it.')
    if (!action.confirmed) throw new Error('Confirm starting another job from the current plan.')
    useApp.setState((current) => ({
      plan: currentPlan,
      submitKeys: { ...current.submitKeys, [currentPlan.kind]: crypto.randomUUID() },
      submitted: { ...current.submitted, [currentPlan.kind]: false },
    }))
    return dispatch({ type: 'submitPlan' })
  }
  if (action.type === 'retryFailed' && !action.confirmed)
    throw new Error('Confirm starting a job for the missing outputs.')
  if (state.busy) throw new Error('Wait for the current action, or stop it first.')
  const controller = new AbortController()
  active = controller
  const version = state.version
  const requestVersion = state.requestVersion
  const selectionVersion = state.selectionVersion
  const futureVersion = state.futureVersion
  useApp.setState({
    busy: true,
    error: '',
    ...(action.type === 'previewSpatial' ? { spatialPreviewAttemptVersion: requestVersion } : {}),
  })
  // Routine map-driven refreshes stay out of the announced Agent transcript.
  const quiet = QUIET_ACTIONS.has(action.type)
  if (!quiet) state.log(action.type, 'tool')
  try {
    let result: unknown
    if (action.type === 'previewSpatial') {
      const preview = await api.spatialPreview(exploreRequest(state.draft), controller.signal)
      controller.signal.throwIfAborted()
      result = preview
      if (useApp.getState().requestVersion === requestVersion)
        useApp.setState({ spatialPreview: preview, spatialPreviewVersion: requestVersion })
    }
    if (action.type === 'discover') {
      const [preview, discovery] = await Promise.all([
        api.spatialPreview(exploreRequest(state.draft), controller.signal),
        api.discover(exploreRequest(state.draft), controller.signal),
      ])
      controller.signal.throwIfAborted()
      result = discovery
      if (useApp.getState().requestVersion === requestVersion) {
        const selectedDatasets = recommendedSelections(discovery)
        useApp.setState((current) => ({
          spatialPreview: preview,
          spatialPreviewVersion: requestVersion,
          discovery,
          discoveryVersion: requestVersion,
          selectedDatasets,
          // Show documented extents for the recommended datasets unless the user chose overlays.
          selectedCoverageIds: current.selectedCoverageIds.length
            ? current.selectedCoverageIds
            : current.coverageLayers
                .filter((layer) =>
                  selectedDatasets.some(
                    (selection) =>
                      selection.provider === layer.provider && selection.dataset === layer.dataset,
                  ),
                )
                .map((layer) => layer.id),
          draft: { ...current.draft, dataset_selections: selectedDatasets },
          selectionVersion: current.selectionVersion + 1,
          version: current.version + 1,
          stage: discovery.candidates.length ? 'download' : 'explore',
          mode: 'weather',
          plan: current.weatherPlan,
        }))
      }
    }
    if (action.type === 'planWeather') {
      const request = { ...state.draft, dataset_selections: state.selectedDatasets }
      const plan = await api.plan(request, 'weather', controller.signal)
      controller.signal.throwIfAborted()
      result = plan
      const current = useApp.getState()
      if (
        current.requestVersion === requestVersion &&
        current.selectionVersion === selectionVersion
      )
        useApp.setState({
          weatherPlan: plan,
          weatherPlanRequestVersion: requestVersion,
          weatherPlanSelectionVersion: selectionVersion,
          plan: current.stage === 'download' ? plan : current.plan,
          submitKeys: {
            ...current.submitKeys,
            weather: rememberedIntent(plan.plan_hash) || crypto.randomUUID(),
          },
          submitted: { ...current.submitted, weather: false },
        })
    }
    if (action.type === 'planFuture') {
      if (!state.future.baseline.trim())
        throw new Error(
          'Upload a baseline EPW or select Use as baseline on a weather result before planning future weather.',
        )
      const baselineId = state.future.baseline
      const plan = await api.plan(state.future, 'future', controller.signal)
      controller.signal.throwIfAborted()
      result = plan
      const current = useApp.getState()
      if (current.futureVersion === futureVersion && current.future.baseline === baselineId)
        useApp.setState({
          futurePlan: plan,
          futurePlanVersion: futureVersion,
          futurePlanBaselineId: baselineId,
          plan: current.stage === 'project' ? plan : current.plan,
          submitKeys: {
            ...current.submitKeys,
            future: rememberedIntent(plan.plan_hash) || crypto.randomUUID(),
          },
          submitted: { ...current.submitted, future: false },
        })
    }
    if (action.type === 'submitPlan') {
      const kind = state.plan?.kind
      if (!state.plan || !kind || state.submitted[kind])
        throw new Error('Review a current plan before submitting.')
      const key = state.submitKeys[kind] || crypto.randomUUID()
      useApp.setState((current) => ({ submitKeys: { ...current.submitKeys, [kind]: key } }))
      rememberIntent(state.plan.plan_hash, key)
      const job = await api.submit(state.plan, key, controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState((current) => ({
        job,
        artifact: null,
        preview: null,
        visualization: null,
        detail: null,
        jobs: [job, ...current.jobs.filter((item) => item.id !== job.id)],
        downloadJobs:
          state.plan?.kind === 'weather'
            ? [job, ...current.downloadJobs.filter((item) => item.id !== job.id)]
            : current.downloadJobs,
        projectJobs:
          state.plan?.kind === 'future'
            ? [job, ...current.projectJobs.filter((item) => item.id !== job.id)]
            : current.projectJobs,
        submitted: { ...current.submitted, [kind]: current.version === version },
      }))
    }
    if (action.type === 'retryFailed') {
      const job = await api.retry(action.id, crypto.randomUUID(), controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState((current) => ({
        job,
        jobs: [job, ...current.jobs.filter((item) => item.id !== job.id)],
        downloadJobs:
          job.kind === 'weather'
            ? [job, ...current.downloadJobs.filter((item) => item.id !== job.id)]
            : current.downloadJobs,
        projectJobs:
          job.kind === 'future'
            ? [job, ...current.projectJobs.filter((item) => item.id !== job.id)]
            : current.projectJobs,
      }))
    }
    if (action.type === 'selectJob') {
      const job = await api.job(action.id, controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState({
        job,
        artifact: null,
        preview: null,
        visualization: null,
        detail: null,
      })
    }
    if (action.type === 'cancelJob') {
      const job = await api.cancel(action.id, controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState((current) => ({
        job,
        jobs: current.jobs.map((item) => (item.id === job.id ? job : item)),
        downloadJobs: current.downloadJobs.map((item) => (item.id === job.id ? job : item)),
        projectJobs: current.projectJobs.map((item) => (item.id === job.id ? job : item)),
      }))
    }
    if (action.type === 'uploadBaseline' || action.type === 'uploadSignals') {
      if (action.file.size > 5_000_000) throw new Error('Upload exceeds 5 MB')
      const ref =
        action.type === 'uploadBaseline'
          ? await api.upload(action.file, controller.signal)
          : await api.signals(JSON.parse(await action.file.text()), controller.signal)
      controller.signal.throwIfAborted()
      result = ref
      if (action.type === 'uploadBaseline') {
        const visualization = await api.visualization(ref.id, undefined, controller.signal)
        controller.signal.throwIfAborted()
        useApp.setState((current) => ({
          importedArtifacts: [
            ref,
            ...current.importedArtifacts.filter((artifact) => artifact.id !== ref.id),
          ],
          activeWeatherArtifact: ref,
          baselineOrigin: 'upload',
          artifact: ref,
          visualization,
          preview: null,
          future: { ...current.future, baseline: ref.id },
          futureVersion: current.futureVersion + 1,
          version: current.version + 1,
          inspector: {
            ...current.inspector,
            open: !current.inspector.manuallyCollapsed,
          },
        }))
      } else {
        useApp.getState().editFuture({ signals: ref.id })
      }
    }
    if (action.type === 'previewPage') {
      if (!state.artifact) throw Error('Select a weather artifact first.')
      const preview = await api.preview(state.artifact.id, action.start, controller.signal)
      controller.signal.throwIfAborted()
      result = preview
      if (useApp.getState().artifact?.id === state.artifact.id) useApp.setState({ preview })
    }
    if (action.type === 'selectArtifact') {
      useApp.setState((current) => ({
        artifact: action.artifact,
        preview: null,
        visualization: null,
        detail: null,
        inspector:
          current.artifact?.id === action.artifact.id
            ? current.inspector
            : { ...current.inspector, variable: undefined },
      }))
      if (action.artifact.media_type === 'application/vnd.energyplus.epw') {
        const visualization = await api.visualization(
          action.artifact.id,
          action.variables,
          controller.signal,
        )
        controller.signal.throwIfAborted()
        result = visualization
        if (useApp.getState().artifact?.id === action.artifact.id)
          useApp.setState((current) => {
            const inspector = { ...current.inspector, open: !current.inspector.manuallyCollapsed }
            // Projection outputs are inspectable but never replace the Project baseline.
            const eligible = deriveWorkflow(current).eligibleArtifacts.some(
              (artifact) => artifact.id === action.artifact.id,
            )
            if (!eligible) return { visualization, inspector }
            return {
              visualization,
              inspector,
              activeWeatherArtifact: action.artifact,
              baselineOrigin: action.artifact.role === 'baseline' ? 'upload' : 'download',
              future: { ...current.future, baseline: action.artifact.id },
              futureVersion:
                current.future.baseline === action.artifact.id
                  ? current.futureVersion
                  : current.futureVersion + 1,
            }
          })
      } else {
        const detail = await api.jsonArtifact(action.artifact.id, controller.signal)
        controller.signal.throwIfAborted()
        result = detail
        if (useApp.getState().artifact?.id === action.artifact.id) useApp.setState({ detail })
      }
    }
    if (action.type === 'loadCoverage') {
      const coverage = await api.coverage({}, controller.signal)
      controller.signal.throwIfAborted()
      result = coverage
      useApp.setState({ coverageLayers: coverage })
    }
    if (!quiet)
      state.log(
        action.type === 'submitPlan'
          ? 'Job accepted; completion is reported by the server.'
          : `${action.type} completed.`,
      )
    return result
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Operation failed'
    useApp.setState({ error: message })
    state.log(message, 'error')
    throw error
  } finally {
    if (active === controller) active = null
    useApp.setState({ busy: false })
  }
}

export function run(action: AppAction) {
  void dispatch(action).catch(() => {})
}

import { api, type Artifact, type FutureRequest, type WeatherRequest } from '../api/client'
import { rememberedIntent, rememberIntent } from './intent'
import { useApp } from './store'
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
  selectJob: { confirmation: 'none', reversible: true },
  cancelJob: { confirmation: 'job', reversible: false },
  cancelActive: { confirmation: 'none', reversible: true },
  selectArtifact: { confirmation: 'none', reversible: true },
  uploadBaseline: { confirmation: 'none', reversible: false },
  uploadSignals: { confirmation: 'none', reversible: false },
  previewPage: { confirmation: 'none', reversible: true },
  loadCoverage: { confirmation: 'none', reversible: true },
} as const

export type AppAction =
  | { type: 'editQuery'; patch: Partial<WeatherRequest> }
  | { type: 'editFuture'; patch: Partial<FutureRequest> }
  | { type: 'selectDatasets'; selections: DatasetSelection[] }
  | { type: 'navigate'; stage: Stage }
  | {
      type:
        | 'previewSpatial'
        | 'discover'
        | 'planWeather'
        | 'planFuture'
        | 'submitPlan'
        | 'rerunPlan'
        | 'cancelActive'
        | 'loadCoverage'
    }
  | { type: 'runCurrentStage'; confirmed?: boolean }
  | { type: 'selectJob'; id: string }
  | { type: 'cancelJob'; id: string }
  | { type: 'selectArtifact'; artifact: Artifact; variables?: string[] }
  | { type: 'uploadBaseline' | 'uploadSignals'; file: File }
  | { type: 'previewPage'; start: number }

export type Action = AppAction
let active: AbortController | null = null

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
  if (action.type === 'editQuery') return state.edit(action.patch)
  if (action.type === 'editFuture') return state.editFuture(action.patch)
  if (action.type === 'selectDatasets') return state.selectDatasets(action.selections)
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
    if (!state.plan) throw new Error('Review a current plan before rerunning it.')
    useApp.setState({ submitKey: crypto.randomUUID(), submitted: false })
    return dispatch({ type: 'submitPlan' })
  }
  if (state.busy) throw new Error('Wait for the current action, or stop it first.')
  const controller = new AbortController()
  active = controller
  const version = state.version
  const requestVersion = state.requestVersion
  const selectionVersion = state.selectionVersion
  const futureVersion = state.futureVersion
  useApp.setState({ busy: true, error: '' })
  state.log(action.type, 'tool')
  try {
    let result: unknown
    if (action.type === 'previewSpatial') {
      const preview = await api.spatialPreview(state.draft, controller.signal)
      controller.signal.throwIfAborted()
      result = preview
      if (useApp.getState().requestVersion === requestVersion)
        useApp.setState({ spatialPreview: preview, spatialPreviewVersion: requestVersion })
    }
    if (action.type === 'discover') {
      const [preview, discovery] = await Promise.all([
        api.spatialPreview(state.draft, controller.signal),
        api.discover(state.draft, controller.signal),
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
          submitKey: rememberedIntent(plan.plan_hash) || crypto.randomUUID(),
          submitted: false,
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
          submitKey: rememberedIntent(plan.plan_hash) || crypto.randomUUID(),
          submitted: false,
        })
    }
    if (action.type === 'submitPlan') {
      if (!state.plan || state.submitted)
        throw new Error('Review a current plan before submitting.')
      const key = state.submitKey || crypto.randomUUID()
      useApp.setState({ submitKey: key })
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
        submitted: current.version === version,
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
      useApp.setState({
        artifact: action.artifact,
        preview: null,
        visualization: null,
        detail: null,
      })
      if (action.artifact.media_type === 'application/vnd.energyplus.epw') {
        const visualization = await api.visualization(
          action.artifact.id,
          action.variables,
          controller.signal,
        )
        controller.signal.throwIfAborted()
        result = visualization
        if (useApp.getState().artifact?.id === action.artifact.id)
          useApp.setState((current) => ({
            visualization,
            activeWeatherArtifact: action.artifact,
            baselineOrigin: action.artifact.role === 'baseline' ? 'upload' : 'download',
            future: { ...current.future, baseline: action.artifact.id },
            futureVersion:
              current.future.baseline === action.artifact.id
                ? current.futureVersion
                : current.futureVersion + 1,
            inspector: {
              ...current.inspector,
              open: !current.inspector.manuallyCollapsed,
            },
          }))
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

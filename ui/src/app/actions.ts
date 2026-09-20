import { rememberedIntent, rememberIntent } from './intent'
import { api, type Artifact } from '../api/client'
import { useApp } from './store'
export type Action =
  | { type: 'discover' | 'planWeather' | 'planFuture' | 'submitPlan' | 'cancelActive' }
  | { type: 'selectJob'; id: string }
  | { type: 'cancelJob'; id: string }
  | { type: 'selectArtifact'; artifact: Artifact }
  | { type: 'uploadBaseline' | 'uploadSignals'; file: File }
  | { type: 'previewPage'; start: number }
let active: AbortController | null = null
export async function dispatch(action: Action): Promise<unknown> {
  const state = useApp.getState()
  if (action.type === 'cancelActive') {
    active?.abort()
    state.log(
      'Client cancellation requested; server jobs continue. Refresh Results to reconcile submissions.',
    )
    return
  }
  if (state.busy) throw new Error('Wait for the current action, or stop it first.')
  const controller = new AbortController()
  active = controller
  const version = state.version
  useApp.setState({ busy: true, error: '' })
  state.log(action.type, 'tool')
  try {
    let result: unknown
    if (action.type === 'discover') {
      result = await api.discover(state.draft, controller.signal)
      controller.signal.throwIfAborted()
      if (useApp.getState().version === version)
        useApp.setState({ discovery: result as Awaited<ReturnType<typeof api.discover>> })
    }
    if (action.type === 'planWeather' || action.type === 'planFuture') {
      const kind = action.type === 'planFuture' ? 'future' : 'weather'
      if (kind === 'future' && !state.future.baseline.trim())
        throw new Error(
          'Upload a baseline EPW or select Use as baseline on a weather result before planning future weather.',
        )
      const plan = await api.plan(
        kind === 'future' ? state.future : state.draft,
        kind,
        controller.signal,
      )
      controller.signal.throwIfAborted()
      result = plan
      if (useApp.getState().version === version)
        useApp.setState({
          plan,
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
      useApp.setState({
        job,
        artifact: null,
        preview: null,
        detail: null,
        jobs: [job, ...state.jobs.filter((j) => j.id !== job.id)],
        submitted: useApp.getState().version === version,
      })
    }
    if (action.type === 'selectJob') {
      const job = await api.job(action.id, controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState({ job, artifact: null, preview: null, detail: null })
    }
    if (action.type === 'cancelJob') {
      const job = await api.cancel(action.id, controller.signal)
      controller.signal.throwIfAborted()
      result = job
      useApp.setState({ job })
    }
    if (action.type === 'uploadBaseline' || action.type === 'uploadSignals') {
      if (action.file.size > 5_000_000) throw new Error('Upload exceeds 5 MB')
      const ref =
        action.type === 'uploadBaseline'
          ? await api.upload(action.file, controller.signal)
          : await api.signals(JSON.parse(await action.file.text()), controller.signal)
      controller.signal.throwIfAborted()
      result = ref
      useApp
        .getState()
        .editFuture(action.type === 'uploadBaseline' ? { baseline: ref.id } : { signals: ref.id })
    }
    if (action.type === 'previewPage') {
      if (!state.artifact) throw Error('Select a weather artifact first.')
      const preview = await api.preview(state.artifact.id, action.start, controller.signal)
      controller.signal.throwIfAborted()
      result = preview
      if (useApp.getState().artifact?.id === state.artifact.id) useApp.setState({ preview })
    }
    if (action.type === 'selectArtifact') {
      useApp.setState({ artifact: action.artifact, preview: null, detail: null })
      result =
        action.artifact.media_type === 'application/vnd.energyplus.epw'
          ? await api.preview(action.artifact.id, 0, controller.signal)
          : await api.jsonArtifact(action.artifact.id, controller.signal)
      controller.signal.throwIfAborted()
      useApp.setState(
        action.artifact.media_type === 'application/vnd.energyplus.epw'
          ? { preview: result as Awaited<ReturnType<typeof api.preview>> }
          : { detail: result },
      )
    }
    state.log(
      action.type === 'submitPlan'
        ? 'Job accepted; completion is reported by the server.'
        : action.type + ' completed.',
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
export function run(action: Action) {
  void dispatch(action).catch(() => {})
}

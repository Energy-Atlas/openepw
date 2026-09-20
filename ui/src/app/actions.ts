import { api, type Artifact } from '../api/client'
import { useApp } from './store'
export type Action =
  | { type: 'discover' | 'planWeather' | 'planFuture' | 'submitPlan' | 'cancelActive' }
  | { type: 'selectJob'; id: string }
  | { type: 'cancelJob'; id: string }
  | { type: 'selectArtifact'; artifact: Artifact }
  | { type: 'uploadBaseline' | 'uploadSignals'; file: File }
let active: AbortController | null = null
export async function dispatch(action: Action): Promise<unknown> {
  const state = useApp.getState()
  if (action.type === 'cancelActive') {
    active?.abort()
    state.log('Stopped client operation; already submitted server jobs continue.')
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
      if (useApp.getState().version === version)
        useApp.setState({ discovery: result as Awaited<ReturnType<typeof api.discover>> })
    }
    if (action.type === 'planWeather' || action.type === 'planFuture') {
      const kind = action.type === 'planFuture' ? 'future' : 'weather'
      const plan = await api.plan(
        kind === 'future' ? state.future : state.draft,
        kind,
        controller.signal,
      )
      result = plan
      if (useApp.getState().version === version)
        useApp.setState({ plan, submitKey: crypto.randomUUID(), submitted: false })
    }
    if (action.type === 'submitPlan') {
      if (!state.plan || state.submitted)
        throw new Error('Review a current plan before submitting.')
      const key = state.submitKey || crypto.randomUUID()
      useApp.setState({ submitKey: key })
      const job = await api.submit(state.plan, key)
      result = job
      useApp.setState({
        job,
        jobs: [job, ...state.jobs.filter((j) => j.id !== job.id)],
        submitted: true,
      })
    }
    if (action.type === 'selectJob') {
      const job = await api.job(action.id)
      result = job
      useApp.setState({ job })
    }
    if (action.type === 'cancelJob') {
      const job = await api.cancel(action.id)
      result = job
      useApp.setState({ job })
    }
    if (action.type === 'uploadBaseline' || action.type === 'uploadSignals') {
      if (action.file.size > 5_000_000) throw new Error('Upload exceeds 5 MB')
      const ref =
        action.type === 'uploadBaseline'
          ? await api.upload(action.file)
          : await api.signals(JSON.parse(await action.file.text()))
      result = ref
      useApp
        .getState()
        .editFuture(action.type === 'uploadBaseline' ? { baseline: ref.id } : { signals: ref.id })
    }
    if (action.type === 'selectArtifact') {
      useApp.setState({ artifact: action.artifact, preview: null, detail: null })
      result =
        action.artifact.media_type === 'application/vnd.energyplus.epw'
          ? await api.preview(action.artifact.id)
          : await api.jsonArtifact(action.artifact.id)
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

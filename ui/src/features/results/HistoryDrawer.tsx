import { useEffect, useRef, useState, type RefObject } from 'react'
import { api, type Artifact } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { canNavigate, deriveWorkflow } from '../../app/workflow'
import { preferredWeatherArtifact } from '../../app/artifacts'
import { ModalDialog } from '../../shell/ModalDialog'

const terminal = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])

// A completion can land while another action is running; defer instead of dropping it.
function whenIdle(callback: () => void) {
  if (!useApp.getState().busy) return callback()
  const unsubscribe = useApp.subscribe((state) => {
    if (state.busy) return
    unsubscribe()
    callback()
  })
}

// Restores job context after a reload: History weather EPWs become eligible baselines, an
// unfinished job resumes monitoring, and a restored stage that is not unlocked falls back.
export function useJobReconcile() {
  useEffect(() => {
    let alive = true
    function validateStage() {
      const state = useApp.getState()
      if (!canNavigate(deriveWorkflow(state), state.stage)) state.setStage('explore')
    }
    api
      .jobs()
      .then((response) => {
        if (!alive) return
        useApp.setState((current) => {
          const active = current.job
            ? undefined
            : response.items.find((job) => !terminal.has(job.state))
          const known = new Set(current.jobs.map((job) => job.id))
          return {
            jobs: [...current.jobs, ...response.items.filter((job) => !known.has(job.id))],
            cursor: response.next_cursor || null,
            ...(active && {
              job: active,
              downloadJobs:
                active.kind === 'weather'
                  ? [active, ...current.downloadJobs]
                  : current.downloadJobs,
              projectJobs:
                active.kind === 'future' ? [active, ...current.projectJobs] : current.projectJobs,
            }),
          }
        })
      })
      .catch(() => {})
      .finally(() => {
        if (alive) validateStage()
      })
    return () => {
      alive = false
    }
  }, [])
}

export function useJobMonitor() {
  const job = useApp((state) => state.job)
  useEffect(() => {
    if (!job || terminal.has(job.state)) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    const id = job.id
    async function poll() {
      try {
        const next = await api.job(id)
        if (!alive) return
        const state = useApp.getState()
        const project = state.projectJobs.some((item) => item.id === id)
        const download = state.downloadJobs.some((item) => item.id === id)
        const firstWeather = next.bundle?.weather?.[0]
        useApp.setState((current) => ({
          job: current.job?.id === id ? next : current.job,
          jobs: [next, ...current.jobs.filter((item) => item.id !== id)],
          downloadJobs: download
            ? [next, ...current.downloadJobs.filter((item) => item.id !== id)]
            : current.downloadJobs,
          projectJobs: project
            ? [next, ...current.projectJobs.filter((item) => item.id !== id)]
            : current.projectJobs,
          stage: download && terminal.has(next.state) && firstWeather ? 'project' : current.stage,
        }))
        attempts = 0
        if (terminal.has(next.state) && firstWeather) {
          const selected = useApp.getState().artifact?.id
          // Open the backend-ranked EPW for the selected (or first) point, not bundle order.
          const preferred = preferredWeatherArtifact(useApp.getState(), next) ?? firstWeather
          whenIdle(() => {
            // Respect a selection the user made while the completion was deferred.
            if (useApp.getState().artifact?.id === selected)
              run({ type: 'selectArtifact', artifact: preferred })
          })
        } else timer = setTimeout(poll, 1500)
      } catch {
        if (alive) timer = setTimeout(poll, Math.min(1500 * 2 ** ++attempts, 15000))
      }
    }
    timer = setTimeout(poll, 500)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [job?.id, job?.state])
}

export function HistoryDrawer({
  open,
  onClose,
  restoreFocus,
}: {
  open: boolean
  onClose: () => void
  restoreFocus?: RefObject<HTMLElement | null>
}) {
  const state = useApp()
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const loaded = useRef(false)

  useEffect(() => {
    if (!open || loaded.current) return
    loaded.current = true
    setLoading(true)
    api
      .jobs()
      .then((response) =>
        useApp.setState({ jobs: response.items, cursor: response.next_cursor || null }),
      )
      .catch(() => setMessage('History is unavailable. Check the local service connection.'))
      .finally(() => setLoading(false))
  }, [open])

  if (!open) return null
  const artifacts: Artifact[] = state.job?.bundle
    ? [
        ...(state.job.bundle.weather ?? []),
        state.job.bundle.manifest,
        state.job.bundle.qc,
        state.job.bundle.request,
        state.job.bundle.plan,
        ...(state.job.bundle.additional ?? []),
      ]
    : []
  return (
    <ModalDialog
      className="history-drawer"
      ariaLabel="Job history"
      onClose={onClose}
      restoreFocus={restoreFocus}
    >
      <header>
        <div>
          <h2>History</h2>
          <p>Immutable jobs, artifacts, QC, and provenance</p>
        </div>
        <button type="button" aria-label="Close history" onClick={onClose}>
          Close
        </button>
      </header>
      {loading && <p role="status">Loading job history…</p>}
      {message && <p className="warning">{message}</p>}
      {!state.jobs.length && !loading && <p className="empty-inline">No jobs have run yet.</p>}
      <div className="history-jobs">
        {state.jobs.map((job) => (
          <button
            type="button"
            className={state.job?.id === job.id ? 'selected' : ''}
            key={job.id}
            onClick={() => run({ type: 'selectJob', id: job.id })}
          >
            <span className={`badge ${job.state}`}>{job.state.replaceAll('_', ' ')}</span>
            <strong>{job.id.slice(0, 8)}</strong>
            <small>
              {job.completed}/{job.total} outputs
            </small>
          </button>
        ))}
      </div>
      {state.job && (
        <section>
          <h3>Job {state.job.id.slice(0, 8)}</h3>
          <p>
            {state.job.completed} complete, {state.job.failed} failed
          </p>
          {state.job.errors?.map((issue, index) => (
            <p className="error" key={`${issue.code}-${index}`}>
              {issue.code}: {issue.message}
            </p>
          ))}
          <div className="history-artifacts">
            {artifacts.map((artifact) => (
              <div key={artifact.id}>
                <button type="button" onClick={() => run({ type: 'selectArtifact', artifact })}>
                  <span>{artifact.path.split('/').pop()}</span>
                  <small>{artifact.role}</small>
                </button>
                <button
                  type="button"
                  aria-label={`Download ${artifact.role}`}
                  onClick={() => void api.download(artifact)}
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </ModalDialog>
  )
}

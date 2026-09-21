import { useEffect, useState } from 'react'
import type { Job } from '../../api/client'

const active = new Set(['queued', 'running'])

export function isActiveJob(job: Job | null | undefined) {
  return Boolean(job && active.has(job.state))
}

/** Outputs the worker has finished, successfully or not, capped at the planned total. */
export function processedOutputs(job: Job) {
  return Math.min(job.total, job.completed + job.failed)
}

export function progressMessage(job: Job, kind: Job['kind']) {
  const noun = kind === 'future' ? 'projection' : 'EPW'
  if (job.state === 'queued') return 'Queued; waiting for the local worker to start.'
  if (job.state === 'running') {
    const failed = job.failed ? ` · ${job.failed} failed` : ''
    return `${processedOutputs(job)} of ${job.total} ${noun} outputs processed${failed}`
  }
  const summary = `${job.completed} ${noun} ${job.completed === 1 ? 'output' : 'outputs'} created`
  return job.failed ? `${summary} · ${job.failed} failed` : summary
}

function elapsed(since: string | undefined, now: number) {
  if (!since) return ''
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`
}

export function JobProgress({
  job,
  kind,
  compact = false,
}: {
  job: Job
  kind: Job['kind']
  compact?: boolean
}) {
  const running = isActiveJob(job)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])
  const title = kind === 'future' ? 'Generating projections' : 'Downloading weather'
  const label = `${title}: ${progressMessage(job, kind)}`
  // Queued or not yet started work has no measurable fraction, so the bar is indeterminate.
  const determinate = job.state === 'running' && processedOutputs(job) > 0
  // Native <progress> draws nothing when indeterminate once restyled, so this is a styled bar.
  const bar = running ? (
    <div
      className={`progress-bar ${determinate ? '' : 'progress-bar-indeterminate'}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={job.total}
      aria-valuenow={determinate ? processedOutputs(job) : undefined}
    >
      <span
        style={determinate ? { width: `${(100 * processedOutputs(job)) / job.total}%` } : undefined}
      />
    </div>
  ) : null

  if (compact)
    return (
      <span className="job-progress-compact">
        {bar}
        <span>{progressMessage(job, kind)}</span>
      </span>
    )

  return (
    <section
      className={`job-progress ${running ? 'job-progress-active' : ''}`}
      aria-label={running ? title : `${title} result`}
    >
      <header>
        <span className={`badge ${job.state}`}>{job.state.replaceAll('_', ' ')}</span>
        <strong>{running ? title : `Job ${job.id.slice(0, 8)}`}</strong>
        {running && <small>{elapsed(job.submitted_at, now)}</small>}
      </header>
      {bar}
      <p role={running ? 'status' : undefined}>{progressMessage(job, kind)}</p>
      {!running &&
        job.errors?.slice(0, 3).map((issue, index) => (
          <p className="error" key={`${issue.code}-${index}`}>
            {issue.code}: {issue.message}
          </p>
        ))}
    </section>
  )
}

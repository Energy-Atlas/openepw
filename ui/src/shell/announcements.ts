import { useEffect, useRef, useState } from 'react'
import type { Job } from '../api/client'
import type { Stage } from '../app/workflow'

const terminal = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])

export function jobAnnouncement(job: Job) {
  const what = job.kind === 'future' ? 'Projection job' : 'Download job'
  const state = job.state.replaceAll('_', ' ')
  const failed = job.failed ? `, ${job.failed} failed` : ''
  return `${what} ${state}: ${job.completed} of ${job.total} outputs created${failed}.`
}

/**
 * Polite screen-reader announcements for stage changes and job completion. Routine map and
 * preview activity is deliberately not announced.
 */
export function useAnnouncements(stage: Stage, job: Job | null) {
  const [message, setMessage] = useState('')
  const previousStage = useRef(stage)
  const announcedJob = useRef<string | null>(null)

  useEffect(() => {
    if (previousStage.current === stage) return
    previousStage.current = stage
    setMessage(`${stage[0].toUpperCase()}${stage.slice(1)} stage.`)
  }, [stage])

  useEffect(() => {
    if (!job) return
    const active = !terminal.has(job.state)
    const previous = announcedJob.current
    announcedJob.current = `${job.id}:${active ? 'active' : job.state}`
    // Only a job seen running in this session is announced when it finishes; reloads and
    // History selections of finished jobs stay quiet.
    if (!active && previous === `${job.id}:active`) setMessage(jobAnnouncement(job))
  }, [job])

  return message
}

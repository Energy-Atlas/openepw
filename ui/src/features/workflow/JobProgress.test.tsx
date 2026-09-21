import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { JobProgress, processedOutputs, progressMessage } from './JobProgress'

afterEach(cleanup)

const job = (patch: object) =>
  ({
    id: 'job-12345678',
    kind: 'weather',
    state: 'running',
    total: 4,
    completed: 0,
    failed: 0,
    submitted_at: new Date().toISOString(),
    ...patch,
  }) as any

it('shows an indeterminate bar while queued or before the first output', () => {
  render(<JobProgress job={job({ state: 'queued' })} kind="weather" />)
  const bar = screen.getByRole('progressbar')
  expect(bar.hasAttribute('aria-valuenow')).toBe(false)
  expect(bar.className).toContain('progress-bar-indeterminate')
  expect(screen.getByText('Queued; waiting for the local worker to start.')).toBeTruthy()
})

it('reports processed outputs, including failures, as a determinate bar', () => {
  const running = job({ completed: 2, failed: 1 })
  render(<JobProgress job={running} kind="weather" />)
  const bar = screen.getByRole('progressbar')
  expect(bar.getAttribute('aria-valuenow')).toBe('3')
  expect(bar.getAttribute('aria-valuemax')).toBe('4')
  expect((bar.firstElementChild as HTMLElement).style.width).toBe('75%')
  expect(screen.getByRole('status').textContent).toBe('3 of 4 EPW outputs processed · 1 failed')
  expect(screen.getByRole('region', { name: 'Downloading weather' })).toBeTruthy()
})

it('summarizes a finished job without a bar and keeps its errors visible', () => {
  render(
    <JobProgress
      job={job({
        state: 'partially_completed',
        completed: 3,
        failed: 1,
        errors: [{ code: 'SOURCE_UNAVAILABLE', message: 'Gone' }],
      })}
      kind="weather"
    />,
  )
  expect(screen.queryByRole('progressbar')).toBeNull()
  expect(screen.getByText('3 EPW outputs created · 1 failed')).toBeTruthy()
  expect(screen.getByText('SOURCE_UNAVAILABLE: Gone')).toBeTruthy()
})

it('caps processed outputs at the planned total and names projection work', () => {
  expect(processedOutputs(job({ completed: 5, failed: 1 }))).toBe(4)
  expect(progressMessage(job({ completed: 1 }), 'future')).toBe(
    '1 of 4 projection outputs processed',
  )
})

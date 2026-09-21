import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useAnnouncements } from './announcements'

afterEach(cleanup)

function Announcer({ stage, job }: { stage: any; job: any }) {
  return <p role="status">{useAnnouncements(stage, job)}</p>
}

const job = (state: string) =>
  ({ id: 'j1', kind: 'weather', state, total: 8, completed: 6, failed: 2 }) as any

it('announces stage changes but not the initial stage', () => {
  const { rerender } = render(<Announcer stage="explore" job={null} />)
  expect(screen.getByRole('status').textContent).toBe('')
  rerender(<Announcer stage="download" job={null} />)
  expect(screen.getByRole('status').textContent).toBe('Download stage.')
})

it('announces a job finishing only after it was seen running', () => {
  const { rerender } = render(<Announcer stage="download" job={job('running')} />)
  expect(screen.getByRole('status').textContent).toBe('')
  act(() => rerender(<Announcer stage="download" job={job('partially_completed')} />))
  expect(screen.getByRole('status').textContent).toBe(
    'Download job partially completed: 6 of 8 outputs created, 2 failed.',
  )
})

it('stays quiet for a job that was already finished when first seen', () => {
  render(<Announcer stage="project" job={job('completed')} />)
  expect(screen.getByRole('status').textContent).toBe('')
})

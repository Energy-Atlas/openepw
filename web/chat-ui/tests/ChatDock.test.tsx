import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App, sessionKey } from '../src/App'
import { ApiError, type SessionHandlers } from '../src/api'
import { FIXTURES, event, fakeApi, form, messageField, snapshot } from './agentFixtures'

afterEach(() => { cleanup(); sessionStorage.clear() })

describe('chat dock and controls', () => {
  it('keeps the current question in the fixed dock, outside the scrolling log', async () => {
    render(<App api={fakeApi(FIXTURES.plan_review)} />)
    const question = await screen.findByLabelText('Current question')
    expect(question.closest('.chat-dock')).not.toBeNull()
    expect(screen.getByRole('log').contains(question)).toBe(false)
  })

  it('shows Working and no actions while a turn runs', async () => {
    render(<App api={fakeApi({ ...FIXTURES.plan_review, busy: true })} />)
    expect(await screen.findByRole('status', { name: 'Working' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run reviewed plan' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Your request' })).toBeDisabled()
  })

  it('follows events and the session after each turn from the subscription', async () => {
    let handlers!: SessionHandlers
    const subscribe = vi.fn((_id: string, _after: number, given: SessionHandlers) => { handlers = given; return () => undefined })
    const start = snapshot(form('map_input', 'Where do you need weather?'), { busy: true, cursor: 2 })
    render(<App api={fakeApi(start, { subscribe })} />)
    await waitFor(() => expect(subscribe).toHaveBeenCalledWith('session-1', 2, expect.anything()))
    act(() => {
      handlers.event(event(2, 'assistant', 'already shown'))             // not after the cursor
      handlers.event(event(3, 'user', 'Boston'))
      handlers.event(event(4, 'view', 'Monthly chart', { view_id: 'view-1' }))
      handlers.state({ ...FIXTURES.location_review, id: 'session-1', busy: false })
    })
    const log = screen.getByRole('log')
    expect(log).toHaveTextContent('Boston')
    expect(log).not.toHaveTextContent('already shown')
    expect(await screen.findByRole('button', { name: 'Approve location' })).toBeInTheDocument()
  })

  it('switches mode, shows the request and goes back with the header buttons', async () => {
    const api = fakeApi({ ...FIXTURES.text, model_available: true })
    render(<App api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Guided mode' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-1', { type: 'mode', mode: 'agent' }))
    fireEvent.click(screen.getByRole('button', { name: 'Your request' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-1', { type: 'request' }))
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-1', { type: 'back' }))
  })

  it('offers no mode switch without a model or after the strike limit', async () => {
    render(<App api={fakeApi({ ...FIXTURES.text, model_available: false })} />)
    expect(await screen.findByRole('button', { name: 'Guided mode' })).toBeDisabled()
    cleanup()
    render(<App api={fakeApi({ ...FIXTURES.text, mode: 'guided', downgraded: true })} />)
    expect(await screen.findByRole('button', { name: 'Guided mode' })).toBeDisabled()
  })

  it('shows a refusal such as a rate limit and keeps the form', async () => {
    const input = vi.fn(async () => { throw new ApiError('RATE_LIMIT', 'Too many messages in a minute; wait a moment and try again.', 429) })
    render(<App api={fakeApi(FIXTURES.text, { input })} />)
    fireEvent.change(await messageField(), { target: { value: '2019' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many messages')
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('shows a download offer as links the browser saves', async () => {
    const files = [{ number: 2, label: 'Denver, Colorado · 2016 · openmeteo/era5', artifact_id: 'a'.repeat(32),
      filename: 'openepw-denver-2016.epw', bytes: 1_650_000 }]
    render(<App api={fakeApi(snapshot(null, { events: [event(5, 'download', 'Ready to download:', { files })], cursor: 5 }))} />)
    const link = await screen.findByRole('link', { name: /Denver, Colorado · 2016/ })
    expect(link).toHaveAttribute('href', expect.stringContaining('a'.repeat(32)))
    expect(link).toHaveAttribute('download', 'openepw-denver-2016.epw')
    expect(screen.getByText(/1\.6 MB/)).toBeInTheDocument()
  })

  it('hides the reply area of an ended session', async () => {
    render(<App api={fakeApi({ ...snapshot(null), ended: true })} />)
    expect(await screen.findByText(/This session has ended/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
  })

  it('uploads an EPW for an upload form', async () => {
    const uploadEpw = vi.fn(async () => FIXTURES.upload)
    render(<App api={fakeApi(FIXTURES.upload, { uploadEpw })} />)
    const file = new File(['LOCATION,Ithaca'], 'ithaca.epw', { type: 'text/plain' })
    fireEvent.change(await screen.findByLabelText('EPW file'), { target: { files: [file] } })
    await waitFor(() => expect(uploadEpw).toHaveBeenCalledWith('session-1', file))
  })

  it('shows one card for the jobs of a request with their combined progress', async () => {
    const running = snapshot(null, { job_ids: ['a', 'b'] })
    const job = vi.fn(async (id: string) => id === 'a'
      ? { id: 'a', state: 'completed', total: 2, completed: 2, failed: 0 }
      : { id: 'b', state: 'running', total: 1, completed: 0, failed: 0 })
    render(<App api={fakeApi(running, { job })} />)
    const card = await screen.findByLabelText('Current weather job')
    await waitFor(() => expect(card).toHaveTextContent('running · 2/3 outputs · 0 failed'))
    expect(card).toHaveTextContent('Weather jobs (2)')
    expect(card).toHaveTextContent('Finished outputs can be downloaded now')
  })

  it('counts each output once after a retry replaced a failure', async () => {
    const row = (status: string, artifact: string | null) => ({ output_id: 'out-boston', occurrence_index: 0,
      period_start: '2016-01-01', status, artifact_id: artifact, dataset_selection: { provider: 'openmeteo', dataset: 'era5' } })
    const jobs: Record<string, unknown> = {
      first: { id: 'first', state: 'partially_completed', total: 2, completed: 1, failed: 1,
        bundle: { weather: [{ id: 'denver', role: 'weather', path: 'd.epw' }], manifest: { id: 'm1' } } },
      retry: { id: 'retry', state: 'completed', total: 1, completed: 1, failed: 0,
        bundle: { weather: [{ id: 'boston', role: 'weather', path: 'b.epw' }], manifest: { id: 'm2' } } } }
    const manifests: Record<string, unknown> = {
      m1: { batch_rows: [row('failed', null), { ...row('succeeded', 'denver'), output_id: 'out-denver', occurrence_index: 1 }],
        output_mapping: [] },
      m2: { batch_rows: [row('succeeded', 'boston')], output_mapping: [] } }
    const api = fakeApi(snapshot(null, { job_ids: ['first', 'retry'], finished_job_ids: ['first', 'retry'] }), {
      job: vi.fn(async (id: string) => jobs[id]), manifest: vi.fn(async (id: string) => manifests[id]) })
    render(<App api={api} />)
    const card = await screen.findByLabelText('Current weather job')
    await waitFor(() => expect(card).toHaveTextContent('2/2 outputs · 0 failed'))
  })

  it('resumes the saved session and starts over only after asking', async () => {
    sessionStorage.setItem(sessionKey, 'session-1')
    const api = fakeApi(FIXTURES.text)
    render(<App api={api} />)
    await screen.findByLabelText('Current question')
    expect(api.get).toHaveBeenCalledWith('session-1')
    expect(api.create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    const confirm = screen.getByRole('alertdialog', { name: 'Start over?' })
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
    expect(api.create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    fireEvent.click(within(screen.getByRole('alertdialog', { name: 'Start over?' })).getByRole('button', { name: 'Start over' }))
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
  })

  it('keeps Start over beside the dock, outside the message form', async () => {
    render(<App api={fakeApi(FIXTURES.text)} />)
    const field = await messageField()
    const reset = screen.getByRole('button', { name: 'Start over' })
    expect(field.closest('form')!.contains(reset)).toBe(false)
    expect(reset.closest('.dock-reset')!.parentElement).toHaveClass('chat-dock')
  })
})

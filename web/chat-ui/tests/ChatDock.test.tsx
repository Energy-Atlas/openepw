import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { ChatApi } from '../src/api'
import type { SessionSnapshot } from '../src/types'

type Card = NonNullable<SessionSnapshot['active_card']>

function state(card: Card | null, extra: Partial<SessionSnapshot> = {}): SessionSnapshot {
  return { id: 'test', revision: card?.revision ?? 1, facts: {}, events: card ? [
    { id: 1, type: 'question', text: card.prompt }] : [], active_card: card, view_ids: [], ...extra }
}

function api(snapshot: SessionSnapshot, extra: Record<string, unknown> = {}): ChatApi {
  return { create: vi.fn(async () => snapshot), get: async () => snapshot,
    catalogMap: async () => ({ schema: 'catalog-map-1', snapshot: null, layers: [], unmapped: [] }),
    ...extra } as unknown as ChatApi
}

afterEach(() => sessionStorage.clear())

describe('chat dock and controls', () => {
  it('keeps the current question with its options in the fixed dock, outside the scrolling log', async () => {
    const card: Card = { id: 'p', revision: 2, kind: 'choice', prompt: 'Which weather product?',
      options: [{ id: 'historical', label: 'Actual-year weather', detail: 'ERA5, NSRDB, NOAA ISD' }] }
    render(<App api={api(state(card))} />)
    const question = await screen.findByLabelText('Current question')
    expect(question.closest('.chat-dock')).not.toBeNull()
    expect(screen.getByRole('log').contains(question)).toBe(false)
    expect(within(screen.getByRole('group', { name: 'Reply options' })).getByRole('button', {
      name: /Actual-year weather.*ERA5, NSRDB, NOAA ISD/ })).toBeInTheDocument()
  })

  it('uses icon buttons for send and confirm and adapts the hint to the question', async () => {
    render(<App api={api(state({ id: 'y', revision: 1, kind: 'text', prompt: 'Which actual year or years?' }))} />)
    const send = await screen.findByRole('button', { name: 'Send' })
    expect(send.querySelector('svg')).not.toBeNull()
    expect(send.textContent).toBe('')
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveAttribute('placeholder', 'e.g. 2018 or 2016–2018')
  })

  it('shows a tick confirm when typing an Other answer', async () => {
    render(<App api={api(state({ id: 'c', revision: 1, kind: 'choice', prompt: 'Which weather product?',
      options: [{ id: 'tmy', label: 'TMY reference' }] }))} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Other — type an answer' }))
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm.querySelector('svg')).not.toBeNull()
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveAttribute('placeholder', 'Type another answer')
  })

  it('never shows a server waiting window while a turn is queued', async () => {
    let finish!: (value: SessionSnapshot) => void
    const sendTurn = vi.fn((_id, _text, _revision, _key, onQueue) => {
      onQueue?.({ queue_id: 'q', state: 'queued', position: 0 })
      return new Promise(resolve => { finish = resolve })
    })
    const initial = state(null)
    render(<App api={api(initial, { sendTurn })} />)
    fireEvent.change(await screen.findByRole('textbox', { name: 'Message' }), { target: { value: 'Boston' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(sendTurn).toHaveBeenCalled())
    expect(screen.queryByText(/Withdraw waiting message|Waiting on server/)).not.toBeInTheDocument()
    finish({ ...initial, revision: 2 })
  })

  it('hides plan actions while an action is running', async () => {
    let finish!: (value: SessionSnapshot) => void
    const prepare = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const review = state({ id: 'r', revision: 3, kind: 'plan_review', prompt: 'Assess options and review a plan' })
    render(<App api={api(review, { prepare })} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Assess and review plan' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Assess and review plan' })).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Type a correction' })).not.toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Working' })).toBeInTheDocument()
    finish({ ...review, revision: 4 })
  })

  it('has no text input while a weather job is running', async () => {
    const running = state(null, { job_id: 'job-1' })
    const job = vi.fn(async () => ({ id: 'job-1', state: 'running', total: 2, completed: 0, failed: 0 }))
    render(<App api={api(running, { job })} />)
    await screen.findByLabelText('Current weather job')
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
  })

  it('renders assistant markdown and the plan summary as bullets', async () => {
    const review = state({ id: 'r', revision: 3, kind: 'plan_review', prompt: 'Review these outputs, then select Run',
      data: { plan_hash: 'a'.repeat(64), summary: '- **Boston** · 2018 · openmeteo/era5 · planned' } },
    { events: [{ id: 1, type: 'message', text: 'Previewed places:\n1. **Boston**\n2. Denver', data: { role: 'assistant' } }] })
    render(<App api={api(review)} />)
    const question = await screen.findByLabelText('Current question')
    expect(within(question).getByRole('listitem')).toHaveTextContent('Boston · 2018 · openmeteo/era5 · planned')
    expect(within(question).getByText('Boston').tagName).toBe('STRONG')
    expect(within(screen.getByRole('log')).getAllByRole('listitem')).toHaveLength(2)
  })

  it('rolls back from an earlier agent message and can start over', async () => {
    const current = state({ id: 'y', revision: 5, kind: 'text', prompt: 'Which actual year or years?' }, { events: [
      { id: 1, type: 'question', text: 'Which weather product?' },
      { id: 2, type: 'message', text: 'Actual-year weather', data: { role: 'user' } },
      { id: 3, type: 'question', text: 'Which actual year or years?' }] })
    const back = vi.fn(async () => ({ ...current, revision: 6, active_card: null }))
    const client = api(current, { back })
    render(<App api={client} />)
    expect(screen.queryByRole('button', { name: 'Go back one step' })).not.toBeInTheDocument()
    const earlier = (await screen.findByText('Which weather product?')).closest('article')!
    expect(within(screen.getByRole('log')).getAllByRole('button', { name: 'Roll back to here' })).toHaveLength(1)
    fireEvent.click(within(earlier).getByRole('button', { name: 'Roll back to here' }))
    await waitFor(() => expect(back).toHaveBeenCalledWith('test', 5, expect.any(String), 1))
    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    await waitFor(() => expect(client.create).toHaveBeenCalledTimes(2))
  })

  it('summarises a chosen location for approval or a typed correction', async () => {
    const review = state({ id: 'l', revision: 4, kind: 'location_review', prompt: 'Is this the right location?',
      data: { summary: '**Cambridge, Massachusetts** · 42.3700, -71.1100' } },
    { facts: { location: { id: 'cambridge', name: 'Cambridge, Massachusetts', lat: 42.37, lon: -71.11 } } })
    const approveLocation = vi.fn(async () => ({ ...review, revision: 5, active_card: null }))
    const sendTurn = vi.fn(async () => ({ ...review, revision: 5 }))
    render(<App api={api(review, { approveLocation, sendTurn })} />)
    const question = await screen.findByLabelText('Current question')
    expect(within(question).getByText('Cambridge, Massachusetts').tagName).toBe('STRONG')
    expect(within(question).getByText(/42\.3700, -71\.1100/)).toBeInTheDocument()
    const message = screen.getByRole('textbox', { name: 'Message' })
    expect(message).toHaveAttribute('placeholder', 'Or describe a correction')
    fireEvent.click(screen.getByRole('button', { name: 'Approve location' }))
    await waitFor(() => expect(approveLocation).toHaveBeenCalledWith('test', 4, expect.any(String)))
  })

  it('asks to approve a place list, with list edits as the correction', async () => {
    const review = state({ id: 'l', revision: 6, kind: 'location_review', prompt: 'Are these the right locations?',
      data: { summary: '**2 places** · Boston; Denver', several: true } })
    const approveLocation = vi.fn(async () => ({ ...review, revision: 7, active_card: null }))
    render(<App api={api(review, { approveLocation })} />)
    expect(await screen.findByRole('textbox', { name: 'Message' })).toHaveAttribute('placeholder', 'Or edit the list, e.g. remove 3')
    fireEvent.click(screen.getByRole('button', { name: 'Approve locations' }))
    await waitFor(() => expect(approveLocation).toHaveBeenCalledWith('test', 6, expect.any(String)))
  })

  it('ticks several products of one kind in a dialog with info popups instead of descriptions', async () => {
    const card: Card = { id: 'p', revision: 8, kind: 'choice', prompt: 'Which weather product?', options: [
      { id: 'era5-openmeteo', label: 'ERA5 actual year · Open-Meteo', detail: '25 km grid', group: 'actual' },
      { id: 'nsrdb-actual', label: 'NSRDB actual year · GOES v4', detail: '4 km grid', group: 'actual' },
      { id: 'onebuilding:TMYx.2009-2023', label: 'OneBuilding TMYx.2009-2023', detail: 'station file', group: 'typical' }],
    data: { field: 'product', availability: { years: [2025], years_assumed: true, omitted_locations: 0, locations: [
      { index: 0, lat: 42.4, lon: -76.5, products: [] }] } } }
    const chooseProducts = vi.fn(async () => ({ ...state(card), revision: 9, active_card: null }))
    render(<App api={api(state(card), { chooseProducts })} />)
    const dialog = await screen.findByRole('region', { name: 'Choose weather products' })
    expect(within(dialog).getByText('Actual year')).toBeInTheDocument()
    expect(within(dialog).getByText('Typical year')).toBeInTheDocument()
    expect(within(dialog).queryByText('4 km grid')).not.toBeInTheDocument()          // no descriptions inline
    const info = within(dialog).getByRole('button', { name: 'About NSRDB actual year · GOES v4' })
    fireEvent.mouseEnter(info)
    expect(screen.getByRole('tooltip')).toHaveTextContent('4 km grid')
    fireEvent.mouseLeave(info)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Current question')).toHaveTextContent('Map tags show availability for 2025')
    const confirm = within(dialog).getByRole('button', { name: 'Confirm product' })
    expect(confirm).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'ERA5 actual year · Open-Meteo' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'NSRDB actual year · GOES v4' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'OneBuilding TMYx.2009-2023' }))    // other kind
    expect(within(dialog).getByRole('checkbox', { name: 'ERA5 actual year · Open-Meteo' })).not.toBeChecked()
    expect(within(dialog).getByRole('status')).toHaveTextContent('separate requests')
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'OneBuilding TMYx.2009-2023' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'ERA5 actual year · Open-Meteo' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'NSRDB actual year · GOES v4' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm 2 products' }))
    await waitFor(() => expect(chooseProducts).toHaveBeenCalledWith('test', 8, ['era5-openmeteo', 'nsrdb-actual'],
      expect.any(String)))
  })
})


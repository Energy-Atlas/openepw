import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { FormKind } from '../src/types'
import { FIXTURES, event, fakeApi, form, messageField, snapshot } from './agentFixtures'

afterEach(() => { cleanup(); sessionStorage.clear() })

describe('map-first shell', () => {
  it('opens one chat over a full-canvas map', async () => {
    render(<App api={fakeApi(snapshot(null))} />)
    expect(screen.getByLabelText('Weather map')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Weather chat' })).toBeInTheDocument()
    expect(await messageField()).toBeInTheDocument()
  })

  it('shows a disabled message field until a session is open', async () => {
    let open!: (value: ReturnType<typeof snapshot>) => void
    const api = fakeApi(snapshot(null), { create: vi.fn(() => new Promise(resolve => { open = resolve })) })
    render(<App api={api} />)
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled()
    open(snapshot(null))                                     // the next test opens its own session
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled())
  })

  it('has no scene panel or brand box over the map', () => {
    render(<App api={fakeApi(snapshot(null))} />)
    expect(screen.queryByRole('region', { name: 'Map scene controls' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '3D view' })).not.toBeInTheDocument()
  })

  it('hides attachment and map input for now', async () => {
    render(<App api={fakeApi(FIXTURES.map_input)} />)
    expect(await messageField()).toBeInTheDocument()
    expect(screen.queryByLabelText('Attach EPW or GeoJSON')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pick geography on map' })).not.toBeInTheDocument()
  })

  it('lists every Stage 1 catalog layer with a toggle before a request is assessed', async () => {
    const layer = (id: string, kind: string, label: string) => ({ id, kind, label, caveat: `${label} caveat`,
      count: 3, evidence_dates: ['2026-09-23'], points: [], rects: [], bounds: [-180, -89, 180, 89] })
    const api = fakeApi(snapshot(null), { catalogMap: async () => ({ schema: 'catalog-map-1', snapshot: null,
      layers: [layer('noaa', 'stations', 'NOAA ISD stations'), layer('onebuilding', 'sites', 'OneBuilding published EPWs'),
        layer('era5', 'extent', 'ERA5 global reanalysis')],
      unmapped: [{ provider: 'nsrdb', dataset: 'aggregate', reason: 'none' }] }) })
    render(<App api={api} />)
    const legend = await screen.findByLabelText('Data availability scope')
    for (const name of ['NOAA ISD stations', 'OneBuilding published EPWs', 'ERA5 global reanalysis'])
      expect(screen.getByRole('checkbox', { name: new RegExp(name) })).toBeChecked()
    fireEvent.mouseEnter(within(legend).getByRole('button', { name: 'About these layers' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('No reviewed geometry: nsrdb/aggregate')
  })

  it('renders a tool call and its result as one outlined line in words', async () => {
    const state = snapshot(null, { events: [
      event(1, 'tool', 'weather_geocode', { tool: 'weather_geocode', phase: 'call', by: 'host' }),
      event(2, 'tool', 'Found 2 places\nmore detail', { tool: 'weather_geocode', phase: 'result', by: 'host' })] })
    const { container } = render(<App api={fakeApi(state)} />)
    await screen.findByText('Finding the place')
    const lines = container.querySelectorAll('.tool-line')
    expect(lines).toHaveLength(1)
    expect(lines[0].closest('.chat-event')).toBeNull()
    expect(lines[0]).toHaveTextContent('Finding the place · Found 2 places')
    expect(lines[0]).not.toHaveTextContent('more detail')
  })

  it('shows the person, the agent, notices and errors, but not form events', async () => {
    const state = snapshot(null, { events: [
      event(1, 'form', 'Where do you need weather?', { form: {} }),
      event(2, 'user', 'AMY 2018 for Ithaca'),
      event(3, 'assistant', 'Checking **Ithaca**.'),
      event(4, 'notice', 'Switched to guided mode (budget).', { code: 'MODEL_UNAVAILABLE' }),
      event(5, 'error', 'GATE_REQUIRED: review the location first', { code: 'GATE_REQUIRED' })] })
    render(<App api={fakeApi(state)} />)
    const log = await screen.findByRole('log')
    await waitFor(() => expect(log).toHaveTextContent('AMY 2018 for Ithaca'))
    expect(within(log).getByText('Ithaca').tagName).toBe('STRONG')
    expect(log.querySelector('.notice-event')).toHaveTextContent('Switched to guided mode')
    expect(log.querySelector('.error-event')).toHaveTextContent('GATE_REQUIRED')
    expect(log).not.toHaveTextContent('Where do you need weather?Where')
  })

  it('never renders raw HTML or unsafe links from model text', async () => {
    const state = snapshot(null, { events: [event(1, 'assistant',
      '<img src=x onerror="alert(1)"> [docs](https://nrel.gov) [bad](javascript:alert(1))')] })
    const { container } = render(<App api={fakeApi(state)} />)
    const link = await screen.findByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(container.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link', { name: 'bad' })?.getAttribute('href') ?? '').not.toContain('javascript')
  })
})

describe('every form kind from the server fixture', () => {
  const controls: Record<FormKind, () => HTMLElement> = {
    map_input: () => screen.getByRole('textbox', { name: 'Message' }),
    text: () => screen.getByRole('textbox', { name: 'Message' }),
    choice: () => screen.getByRole('group', { name: 'Reply options' }),
    location_review: () => screen.getByRole('button', { name: /Approve location/ }),
    product_choice: () => screen.getByRole('region', { name: 'Choose weather products' }),
    plan_review: () => screen.getByRole('button', { name: 'Run reviewed plan' }),
    request_summary: () => screen.getByRole('button', { name: 'Confirm request' }),
    upload: () => screen.getByLabelText('EPW file'),
  }
  for (const kind of Object.keys(controls) as FormKind[]) {
    it(`renders ${kind}`, async () => {
      const state = FIXTURES[kind]
      expect(state.form?.kind).toBe(kind)
      render(<App api={fakeApi(state)} />)
      const card = await screen.findByLabelText('Current question')
      expect(within(card).getByRole('heading', { name: state.form!.prompt })).toBeInTheDocument()
      expect(controls[kind]()).toBeInTheDocument()
    })
  }
})

describe('answers', () => {
  it('numbers place candidates and waits for Confirm before answering', async () => {
    const state = FIXTURES.choice
    const api = fakeApi(state)
    render(<App api={api} />)
    const second = state.form!.options[1]
    const option = await screen.findByRole('button', { name: new RegExp(second.label) })
    expect(option.querySelector('.option-number')).toHaveTextContent('2')
    fireEvent.click(option)
    expect(api.input).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', { type: 'answer', answer: {
      interaction_id: state.form!.id, revision: state.form!.revision, choice_ids: [second.id] } }))
  })

  it('answers other choices at once, and Other opens the text field', async () => {
    const state = snapshot(form('choice', 'What next?', { options: [{ id: 'new', label: 'Start a new weather request' }] }))
    const api = fakeApi(state)
    render(<App api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start a new weather request' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', expect.objectContaining({
      answer: expect.objectContaining({ choice_ids: ['new'] }) })))
    cleanup()
    render(<App api={fakeApi(state)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Other — type an answer' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Back to options' }))
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
  })

  it('approves a location review, or sends a typed correction as text', async () => {
    const state = FIXTURES.location_review
    const api = fakeApi(state)
    render(<App api={api} />)
    const message = await messageField()
    expect(message).toHaveAttribute('placeholder', 'Or describe a correction')
    expect(screen.getByLabelText('Current question')).toHaveTextContent('Springfield')
    fireEvent.change(message, { target: { value: 'use Boston instead' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', { type: 'text', text: 'use Boston instead' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve location' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-1', expect.objectContaining({
      answer: expect.objectContaining({ approve: true }) })))
  })

  it('confirms the ticked products, starting from the preselection', async () => {
    const base = FIXTURES.product_choice
    const preselected = base.form!.options[0].id
    const state = { ...base, form: { ...base.form!, data: { ...base.form!.data, selected: [preselected] } } }
    const api = fakeApi(state)
    render(<App api={api} />)
    const dialog = await screen.findByRole('region', { name: 'Choose weather products' })
    // Its own panel, not inside the reply pills (staging, 2026-11-02: pill styles reached the info icons).
    expect(dialog.closest('.reply-options')).toBeNull()
    expect(within(dialog).getByText('Actual year')).toBeInTheDocument()
    const first = within(dialog).getByRole('checkbox', { name: base.offers[0].label })
    expect(first).toBeChecked()
    fireEvent.click(within(dialog).getByRole('checkbox', { name: base.offers[1].label }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm 2 products' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', expect.objectContaining({
      answer: expect.objectContaining({ choice_ids: [preselected, base.offers[1].id] }) })))
  })

  it('runs a reviewed plan or changes one part of the request', async () => {
    const state = FIXTURES.plan_review
    const api = fakeApi(state)
    render(<App api={api} />)
    const card = await screen.findByLabelText('Current question')
    expect(within(card).queryByText('Your request:')).toBeNull()          // the parts list replaces the text copy
    expect(within(card).getAllByText('Years')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Change years' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', expect.objectContaining({
      answer: expect.objectContaining({ choice_ids: ['change:years'] }) })))
    fireEvent.click(screen.getByRole('button', { name: 'Run reviewed plan' }))
    await waitFor(() => expect(api.input).toHaveBeenLastCalledWith('session-1', expect.objectContaining({
      answer: expect.objectContaining({ approve: true }) })))
  })

  it('shows each part of the request with its status on the summary', async () => {
    const state = FIXTURES.request_summary
    render(<App api={fakeApi(state)} />)
    const card = await screen.findByLabelText('Current question')
    for (const part of state.parts) expect(card).toHaveTextContent(part.label)
    expect(card).toHaveTextContent('confirmed')
    expect(within(screen.getByRole('group', { name: 'Change one part' })).getAllByRole('button').length)
      .toBe(state.form!.options.length)
  })

  it('sends free text as a message and hints the years form', async () => {
    const state = FIXTURES.text
    const api = fakeApi(state)
    render(<App api={api} />)
    const message = await messageField()
    expect(message.getAttribute('placeholder')).toContain('2018')
    fireEvent.change(message, { target: { value: '2019' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(api.input).toHaveBeenCalledWith('session-1', { type: 'text', text: '2019' }))
  })
})

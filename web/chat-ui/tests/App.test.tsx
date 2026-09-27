import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { ChatApi } from '../src/api'
import type { SessionSnapshot } from '../src/types'

function cardState(card: NonNullable<SessionSnapshot['active_card']>): SessionSnapshot {
  return { id: 'test', revision: card.revision, facts: {}, events: [
    { id: 1, type: 'question', text: card.prompt }], active_card: card, view_ids: [] }
}

function apiFor(state: SessionSnapshot): ChatApi {
  return { create: async () => state, get: async () => state,
    catalogScopes: async () => ({ snapshot: null, scopes: [], unmapped: [] }) } as unknown as ChatApi
}

describe('map-first shell', () => {
  it('opens one chat over a full-canvas map without a mode choice', () => {
    render(<App />)
    expect(screen.getByLabelText('Weather map')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Weather chat' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
    expect(screen.queryByText('Guided workflow')).not.toBeInTheDocument()
  })

  it('has no scene panel or brand box over the map', () => {
    render(<App />)
    expect(screen.queryByRole('region', { name: 'Map scene controls' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '3D view' })).not.toBeInTheDocument()
    expect(screen.queryByText('Weather across places and years')).not.toBeInTheDocument()
  })

  it('shows geography tools only while map input is active', () => {
    render(<App />)
    expect(screen.queryByRole('button', { name: 'Choose point' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pick geography on map' }))
    expect(screen.getByRole('toolbar', { name: 'Pick geography' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose point' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close map input' }))
    expect(screen.queryByRole('toolbar', { name: 'Pick geography' })).not.toBeInTheDocument()
  })

  it('uses one chat attachment control instead of header upload buttons', () => {
    render(<App />)
    expect(screen.getByLabelText('Attach EPW or GeoJSON')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload EPW for analysis' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload GeoJSON area or points' })).not.toBeInTheDocument()
  })

  it('lists catalog scope layers before a weather request is assessed', async () => {
    const state: SessionSnapshot = { id: 'test', revision: 0, facts: {}, events: [],
      active_card: null, view_ids: [] }
    const api = { create: async () => state, get: async () => state,
      catalogScopes: async () => ({ snapshot: null, unmapped: [{ provider: 'noaa', dataset: 'isd' }],
        scopes: [{ provider: 'cds', dataset: 'era5', footprint: [0, -89, 360, 89],
          longitude_convention: '0_360', evidence_bases: ['documentation'],
          evidence_dates: ['2026-09-25'] }] }) } as unknown as ChatApi
    render(<App api={api} />)
    expect(await screen.findByLabelText('Data availability scope')).toHaveTextContent('cds/era5')
    expect(screen.getByLabelText('Data availability scope')).toHaveTextContent('1 source dataset lacks mapped scope')
  })

  it('shows the current choice once as an agent turn', async () => {
    render(<App api={apiFor(cardState({ id: 'choice', revision: 1, kind: 'choice', prompt: 'Which weather product?',
      options: [{ id: 'historical', label: 'Actual-year weather' }] }))} />)
    await screen.findByRole('heading', { name: 'Which weather product?' })
    expect(screen.getAllByText('Which weather product?')).toHaveLength(1)
    expect(screen.getByRole('group', { name: 'Reply options' })).toHaveTextContent('Actual-year weather')
  })

  it('replaces the text field with the options of a choice card until Other is chosen', async () => {
    render(<App api={apiFor(cardState({ id: 'choice', revision: 1, kind: 'choice', prompt: 'Which weather product?',
      options: [{ id: 'historical', label: 'Actual-year weather' }] }))} />)
    await screen.findByRole('button', { name: 'Actual-year weather' })
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Other — type an answer' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Back to options' }))
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
  })

  it('offers review actions instead of text while a plan is under review', async () => {
    render(<App api={apiFor(cardState({ id: 'review', revision: 2, kind: 'plan_review', prompt: 'Review the plan' }))} />)
    await screen.findByRole('button', { name: 'Assess and review plan' })
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Type a correction' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('offers map input for a map card with typed coordinates as an alternative', async () => {
    render(<App api={apiFor(cardState({ id: 'where', revision: 1, kind: 'map', prompt: 'Where?' }))} />)
    await screen.findByRole('button', { name: 'Choose on map' })
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Choose on map' }))
    expect(screen.getByRole('toolbar', { name: 'Pick geography' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Type coordinates' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('queues and withdraws a second message while a turn is running', async () => {
    const state: SessionSnapshot = { id: 'test', revision: 0, facts: {}, events: [],
      active_card: null, view_ids: [] }
    let finish!: (value: SessionSnapshot) => void
    const first = new Promise<SessionSnapshot>(resolve => { finish = resolve })
    const sendTurn = vi.fn().mockReturnValue(first)
    const api = { create: async () => state, get: async () => state, sendTurn,
      catalogScopes: async () => ({ snapshot: null, scopes: [], unmapped: [] }) } as unknown as ChatApi
    render(<App api={api} />)
    const input = await screen.findByRole('textbox', { name: 'Message' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled())
    fireEvent.change(input, { target: { value: 'Cambridge 2018' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    fireEvent.change(input, { target: { value: 'Actually 2019' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByLabelText('Waiting messages')).toHaveTextContent('Actually 2019')
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    finish({ ...state, revision: 1 })
    await waitFor(() => expect(screen.queryByLabelText('Waiting messages')).not.toBeInTheDocument())
    expect(sendTurn).toHaveBeenCalledTimes(1)
  })
})

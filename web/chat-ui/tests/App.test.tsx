import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { ChatApi } from '../src/api'
import type { SessionSnapshot } from '../src/types'

describe('map-first shell', () => {
  it('opens one chat over a full-canvas map without a mode choice', () => {
    render(<App />)
    expect(screen.getByLabelText('Weather map')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Weather chat' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument()
    expect(screen.queryByText('Guided workflow')).not.toBeInTheDocument()
  })

  it('offers scene controls without letting terrain run in a flat view', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: '3D view' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Terrain' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '3D view' }))
    expect(screen.getByRole('checkbox', { name: 'Terrain' })).toBeEnabled()
  })

  it('queues and withdraws a second message while a turn is running', async () => {
    const state: SessionSnapshot = { id: 'test', revision: 0, facts: {}, events: [],
      active_card: null, view_ids: [] }
    let finish!: (value: SessionSnapshot) => void
    const first = new Promise<SessionSnapshot>(resolve => { finish = resolve })
    const sendTurn = vi.fn().mockReturnValue(first)
    const api = { create: async () => state, get: async () => state, sendTurn } as unknown as ChatApi
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

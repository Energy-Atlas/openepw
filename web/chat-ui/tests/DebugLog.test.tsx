import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { ChatApi } from '../src/api'
import { debugLogText } from '../src/debugLog'
import type { Diagnostics, SessionSnapshot } from '../src/types'

const session: SessionSnapshot = { id: 'abcdef123456', revision: 4, facts: { years: [2018] }, events: [],
  active_card: { id: 'q', revision: 4, kind: 'text', prompt: 'Where do you need weather?' }, view_ids: [] }
const server: Diagnostics = { version: '0.1.0', server_time: '2026-10-12T20:00:00+00:00',
  security_profile: 'hosted (abc)', catalog_generation: 'gen-1',
  server_log: [{ time: '2026-10-12T19:59:00+00:00', level: 'ERROR', logger: 'uvicorn.error', message: 'Exception in ASGI application' }] }

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => { cleanup(); sessionStorage.clear(); vi.restoreAllMocks() })

describe('debug log', () => {
  it('records calls with the error code and message of failures', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/run')
      ? json(400, { code: 'INVALID_REQUEST', message: 'This plan has no outputs to run' }) : json(200, session))
    const api = new ChatApi('https://example.test', fetcher as unknown as typeof fetch)
    await api.get('abcdef123456')
    await expect(api.run('abcdef123456', 4, 'key')).rejects.toThrow('no outputs')
    expect(api.calls.map(call => [call.method, call.path, call.status])).toEqual([
      ['GET', '/v1/chat/sessions/abcdef123456', 200], ['POST', '/v1/chat/sessions/abcdef123456/run', 400]])
    expect(api.calls[1]).toMatchObject({ code: 'INVALID_REQUEST', message: 'This plan has no outputs to run' })
    const text = debugLogText(session, api.calls, server)
    expect(text).toContain('POST /v1/chat/sessions/abcdef123456/run → 400')
    expect(text).toContain('INVALID_REQUEST: This plan has no outputs to run')
    expect(text).toContain('body: {"revision":4,"idempotency_key":"key"}')
    expect(text).toContain('ERROR uvicorn.error: Exception in ASGI application')
    expect(text).toContain('Session: abcdef123456 · revision 4')
  })

  it('keeps failures when the list is full of polling', async () => {
    let fail = true
    const fetcher = vi.fn(async () => fail ? json(500, { code: 'X', message: 'boom' }) : json(200, {}))
    const api = new ChatApi('', fetcher as unknown as typeof fetch)
    await api.progress('s').catch(() => undefined)
    fail = false
    for (let index = 0; index < 120; index++) await api.progress('s')
    expect(api.calls).toHaveLength(100)
    expect(api.calls[0]).toMatchObject({ status: 500, code: 'X' })
  })

  it('shows Copy log only when the server has diagnostics on', async () => {
    const base = { create: vi.fn(async () => session), get: async () => session,
      catalogMap: async () => ({ schema: 'catalog-map-1', snapshot: null, layers: [], unmapped: [] }), calls: [] }
    const { unmount } = render(<App api={{ ...base, diagnostics: async () => { throw new Error('404') } } as unknown as ChatApi} />)
    await screen.findByLabelText('Current question')
    expect(screen.queryByRole('button', { name: 'Copy log' })).toBeNull()
    unmount()
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<App api={{ ...base, diagnostics: async () => server } as unknown as ChatApi} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Copy log' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(String((writeText.mock.calls[0] as unknown[])[0])).toContain('Exception in ASGI application')
    expect(await screen.findByText('Log copied')).toHaveAttribute('role', 'status')
  })
})

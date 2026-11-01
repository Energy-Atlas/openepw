import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { ChatApi } from '../src/api'
import { debugLogText } from '../src/debugLog'
import type { Diagnostics } from '../src/types'
import { FIXTURES, fakeApi } from './agentFixtures'

const session = { ...FIXTURES.text, id: 'abcdef123456', revision: 4 }
const server: Diagnostics = { version: '0.1.0', server_time: '2026-10-12T20:00:00+00:00',
  security_profile: 'hosted (abc)', catalog_generation: 'gen-1',
  server_log: [{ time: '2026-10-12T19:59:00+00:00', level: 'ERROR', logger: 'uvicorn.error', message: 'Exception in ASGI application' }] }

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => { cleanup(); sessionStorage.clear(); vi.restoreAllMocks() })

describe('debug log', () => {
  it('records calls with the error code and message of failures', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/inputs')
      ? json(409, { code: 'SESSION_BUSY', message: 'The previous input is still being handled.' }) : json(200, session))
    const api = new ChatApi('https://example.test', fetcher as unknown as typeof fetch)
    await api.get('abcdef123456')
    await expect(api.input('abcdef123456', { type: 'back' })).rejects.toThrow('still being handled')
    expect(api.calls.map(call => [call.method, call.path, call.status])).toEqual([
      ['GET', '/v2/agent/sessions/abcdef123456', 200], ['POST', '/v2/agent/sessions/abcdef123456/inputs', 409]])
    expect(api.calls[1]).toMatchObject({ code: 'SESSION_BUSY' })
    const text = debugLogText(session, api.calls, server)
    expect(text).toContain('POST /v2/agent/sessions/abcdef123456/inputs → 409')
    expect(text).toContain('body: {"type":"back"}')
    expect(text).toContain('ERROR uvicorn.error: Exception in ASGI application')
    expect(text).toContain('Session: abcdef123456 · guided mode · revision 4')
  })

  it('keeps failures when the list is full of polling', async () => {
    let fail = true
    const fetcher = vi.fn(async () => fail ? json(500, { code: 'X', message: 'boom' }) : json(200, {}))
    const api = new ChatApi('', fetcher as unknown as typeof fetch)
    await api.job('j').catch(() => undefined)
    fail = false
    for (let index = 0; index < 120; index++) await api.job('j')
    expect(api.calls).toHaveLength(100)
    expect(api.calls[0]).toMatchObject({ status: 500, code: 'X' })
  })

  it('shows Copy log only when the server has diagnostics on', async () => {
    const { unmount } = render(<App api={fakeApi(session, { diagnostics: async () => { throw new Error('404') } })} />)
    await screen.findByLabelText('Current question')
    expect(screen.queryByRole('button', { name: 'Copy log' })).toBeNull()
    unmount()
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<App api={fakeApi(session, { diagnostics: async () => server })} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Copy log' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(String((writeText.mock.calls[0] as unknown[])[0])).toContain('Exception in ASGI application')
    expect(await screen.findByText('Log copied')).toHaveAttribute('role', 'status')
  })
})

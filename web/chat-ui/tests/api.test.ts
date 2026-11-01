import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatApi } from '../src/api'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('chat API client', () => {
  it('loads read-only catalog scopes for the initial map', async () => {
    const data = { snapshot: null, scopes: [], unmapped: [] }
    const fetcher = vi.fn().mockResolvedValue(json(data))
    const api = new ChatApi('', fetcher)
    await expect(api.catalogScopes()).resolves.toEqual(data)
    expect(fetcher).toHaveBeenCalledWith('/v1/catalog/scopes', undefined)
  })

  it('sends one input to /v2 and returns typed errors', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({ code: 'SESSION_BUSY', message: 'Still working' }, 409))
    const api = new ChatApi('', fetcher)
    await expect(api.input('session-1', { type: 'text', text: 'Cambridge 2016' }))
      .rejects.toMatchObject({ code: 'SESSION_BUSY', status: 409 })
    expect(fetcher).toHaveBeenCalledWith('/v2/agent/sessions/session-1/inputs', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ type: 'text', text: 'Cambridge 2016' }) }))
  })

  it('polls events after the cursor where the browser has no EventSource', async () => {
    vi.stubGlobal('EventSource', undefined)
    const state = { id: 'session-1', busy: false }
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ events: [{ seq: 3, type: 'user', text: 'hi', data: {} }], cursor: 3, state }))
      .mockResolvedValue(json({ events: [], cursor: 3, state }))
    const api = new ChatApi('', fetcher)
    const event = vi.fn()
    const seen = vi.fn()
    const stop = api.subscribe('session-1', 2, { event, state: seen })
    await vi.waitFor(() => expect(seen).toHaveBeenCalled())
    expect(fetcher).toHaveBeenCalledWith('/v2/agent/sessions/session-1/events?poll=1&after=2', undefined)
    expect(event).toHaveBeenCalledWith({ seq: 3, type: 'user', text: 'hi', data: {} })
    stop()
  })

  it('streams agent and state frames from an EventSource', () => {
    const listeners: Record<string, (message: { data: string }) => void> = {}
    const close = vi.fn()
    const source = vi.fn(function (this: Record<string, unknown>, url: string) {
      this.url = url
      this.addEventListener = (name: string, listener: (message: { data: string }) => void) => { listeners[name] = listener }
      this.close = close
    })
    vi.stubGlobal('EventSource', source)
    const event = vi.fn()
    const state = vi.fn()
    const stop = new ChatApi('https://host').subscribe('s 1', 5, { event, state })
    expect(source).toHaveBeenCalledWith('https://host/v2/agent/sessions/s%201/events?after=5', { withCredentials: true })
    listeners.agent({ data: JSON.stringify({ seq: 6, type: 'assistant', text: 'ok', data: {} }) })
    listeners.state({ data: JSON.stringify({ id: 's 1', busy: false }) })
    expect(event).toHaveBeenCalledWith(expect.objectContaining({ seq: 6 }))
    expect(state).toHaveBeenCalledWith({ id: 's 1', busy: false })
    stop()
    expect(close).toHaveBeenCalled()
  })
})

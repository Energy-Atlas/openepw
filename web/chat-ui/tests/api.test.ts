import { describe, expect, it, vi } from 'vitest'
import { ChatApi } from '../src/api'

describe('chat API client', () => {
  it('sends a turn with an idempotency key and returns typed errors', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(
      JSON.stringify({ code: 'STALE_REVISION', message: 'Use current question' }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    ))
    const api = new ChatApi('', fetcher)
    await expect(api.sendTurn('session-1', 'Cambridge 2016', 2, 'request-1'))
      .rejects.toMatchObject({ code: 'STALE_REVISION', status: 409 })
    expect(fetcher).toHaveBeenCalledWith('/v1/chat/sessions/session-1/turns/queue', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ text: 'Cambridge 2016', revision: 2, idempotency_key: 'request-1' }),
    }))
  })

  it('resumes the session when a queued turn is complete', async () => {
    const snapshot = { id: 'session-1', revision: 3, facts: {}, events: [], active_card: null }
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ queue_id: 'queued-1', state: 'completed', position: 0 })))
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot)))
    const api = new ChatApi('', fetcher)
    await expect(api.sendTurn('session-1', 'hello', 2, 'request-1')).resolves.toMatchObject(snapshot)
    expect(fetcher).toHaveBeenLastCalledWith('/v1/chat/sessions/session-1', undefined)
  })
})

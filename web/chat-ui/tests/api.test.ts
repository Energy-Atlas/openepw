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
    expect(fetcher).toHaveBeenCalledWith('/v1/chat/sessions/session-1/turns', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ text: 'Cambridge 2016', revision: 2, idempotency_key: 'request-1' }),
    }))
  })
})

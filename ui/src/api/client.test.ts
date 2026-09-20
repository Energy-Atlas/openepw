import { it, expect, vi, afterEach } from 'vitest'
import { api } from './client'
afterEach(() => vi.unstubAllGlobals())
it('does not mistake HTML or an auth failure for success', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(new Response('<html/>', { headers: { 'content-type': 'text/html' } })),
  )
  await expect(api.jobs()).rejects.toThrow(/JSON/)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response('{"detail":"Authentication required"}', {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  )
  await expect(api.jobs()).rejects.toThrow(/Authentication/)
})

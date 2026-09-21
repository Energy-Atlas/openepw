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

it('calls spatial preview, coverage and full artifact visualization contracts', async () => {
  const fetch = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(new Response('{}', { headers: { 'content-type': 'application/json' } })),
    )
  vi.stubGlobal('fetch', fetch)
  const request = { locations: { lat: 1, lon: 2 }, product: 'amy', years: [2024] } as any

  await api.spatialPreview(request)
  await api.coverage({ provider: 'era5', product: 'amy', year: 2024 })
  await api.visualization('artifact/id', ['dry_bulb', 'dni'])

  expect(fetch.mock.calls[0][0]).toBe('/v1/spatial/preview')
  expect(fetch.mock.calls[0][1].method).toBe('POST')
  expect(fetch.mock.calls[1][0]).toBe('/v1/weather/coverage?provider=era5&product=amy&year=2024')
  expect(fetch.mock.calls[2][0]).toBe(
    '/v1/artifacts/artifact%2Fid/visualization?variables=dry_bulb&variables=dni',
  )
})

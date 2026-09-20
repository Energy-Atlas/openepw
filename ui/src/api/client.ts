import type { components } from './schema'
export type Schemas = components['schemas']
export type WeatherRequest = Schemas['WeatherRequest']
export type FutureRequest = Schemas['FutureRequest']
export type Plan = Schemas['WeatherPlan']
export type Job = Schemas['WeatherJob']
export type Artifact = Schemas['ArtifactRef']
let token = ''
export function setToken(value: string) {
  token = value
}
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', 'Bearer ' + token)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.headers.get('content-type')?.includes('application/json'))
    throw new Error('Expected JSON from OpenEPW. Check the backend connection.')
  const data = await response.json()
  if (!response.ok)
    throw new Error(
      (typeof data.message === 'string'
        ? data.message
        : typeof data.detail === 'string'
          ? data.detail
          : 'Request rejected') +
        (data.code ? ' [' + data.code + ']' : '') +
        (Array.isArray(data.fields)
          ? ' � ' + data.fields.map((p: unknown[]) => p.join('.')).join(', ')
          : ''),
    )
  return data as T
}
const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body), signal })
export const api = {
  geocode: (query: string) => post<Schemas['GeocodeResult']>('/v1/geocode', { query }),
  discover: (body: WeatherRequest, signal?: AbortSignal) =>
    post<Schemas['DiscoveryResult']>('/v1/weather/discover', body, signal),
  plan: (body: WeatherRequest | FutureRequest, kind: 'weather' | 'future', signal?: AbortSignal) =>
    post<Plan>(`/v1/${kind}/plan`, body, signal),
  submit: (plan: Plan, key: string, signal?: AbortSignal) =>
    post<Job>(`/v1/${plan.kind}/jobs`, { plan, idempotency_key: key }, signal),
  jobs: (cursor?: string) =>
    request<Schemas['JobListResponse']>(
      '/v1/jobs?limit=20' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
    ),
  job: (id: string, signal?: AbortSignal) =>
    request<Job>('/v1/jobs/' + encodeURIComponent(id), { signal }),
  cancel: (id: string, signal?: AbortSignal) =>
    post<Job>(`/v1/jobs/${encodeURIComponent(id)}/cancel`, {}, signal),
  upload: (file: File, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('file', file)
    return request<Artifact>('/v1/artifacts', { method: 'POST', body: form, signal })
  },
  signals: (records: unknown, signal?: AbortSignal) =>
    post<Artifact>('/v1/artifacts/signals', records, signal),
  preview: (id: string, start = 0, signal?: AbortSignal) =>
    request<Schemas['WeatherPreview']>(
      `/v1/artifacts/${encodeURIComponent(id)}/preview?start=${start}&limit=168`,
      { signal },
    ),
  jsonArtifact: (id: string, signal?: AbortSignal) =>
    request<unknown>('/v1/artifacts/' + encodeURIComponent(id), { signal }),
  async download(artifact: Artifact) {
    const r = await fetch('/v1/artifacts/' + encodeURIComponent(artifact.id), {
      headers: token ? { Authorization: 'Bearer ' + token } : {},
    })
    if (!r.ok) throw new Error('Artifact download failed')
    const url = URL.createObjectURL(await r.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = artifact.path.split('/').pop() || 'artifact'
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

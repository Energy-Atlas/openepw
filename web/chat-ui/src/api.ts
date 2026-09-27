import type { JobManifest, JobSnapshot, SessionSnapshot, ViewPage } from './types'

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message)
  }
}

export class ChatApi {
  constructor(private base = '', private fetcher: typeof fetch = (...args) => fetch(...args)) {}

  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await this.fetcher(`${this.base}${path}`, body === undefined ? undefined : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    const result = await response.json()
    if (!response.ok) throw new ApiError(result.code || 'HTTP_ERROR',
      result.message || 'Request failed', response.status)
    return result as T
  }

  create(): Promise<SessionSnapshot> { return this.request('/v1/chat/sessions', {}) }

  get(id: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}`)
  }

  answer(id: string, revision: number, choice_id: string, key: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/choices`,
      { revision, choice_id, idempotency_key: key })
  }

  prepare(id: string, revision: number, key: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/prepare`,
      { revision, idempotency_key: key })
  }

  run(id: string, revision: number, key: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/run`,
      { revision, idempotency_key: key })
  }

  setGeography(id: string, revision: number, geography: unknown, key: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/geography`,
      { revision, geography, idempotency_key: key })
  }

  job(id: string): Promise<JobSnapshot> { return this.request(`/v1/jobs/${encodeURIComponent(id)}`) }

  artifacts(id: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/artifacts`)
  }

  compact(id: string): Promise<{ id: string; path: string }> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/export/compact`, {})
  }

  cancel(id: string): Promise<JobSnapshot> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/cancel`, {})
  }

  retry(id: string, key: string): Promise<JobSnapshot> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/retry`, { idempotency_key: key })
  }

  artifactUrl(id: string): string { return `${this.base}/v1/artifacts/${encodeURIComponent(id)}` }

  manifest(id: string): Promise<JobManifest> { return this.request(this.artifactUrl(id).slice(this.base.length)) }

  viewCapabilities(): Promise<Record<string, unknown>> { return this.request('/v1/views/capabilities') }

  prepareView(request: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request('/v1/views/prepare', request)
  }

  pageView(id: string, offset = 0, limit = 200): Promise<ViewPage> {
    return this.request(`/v1/views/${encodeURIComponent(id)}/page?offset=${offset}&limit=${limit}`)
  }

  sessionView(id: string, revision: number, key: string, request: Record<string, unknown>, prompt?: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/views`,
      { revision, idempotency_key: key, request, prompt })
  }

  attachUpload(id: string, revision: number, key: string, artifact_id: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/uploads`,
      { revision, idempotency_key: key, artifact_id })
  }

  async upload(file: File): Promise<{ id: string }> {
    const form = new FormData()
    form.append('file', file)
    const response = await this.fetcher(`${this.base}/v1/artifacts`, { method: 'POST', body: form })
    const result = await response.json()
    if (!response.ok) throw new ApiError(result.code || 'HTTP_ERROR', result.message || 'Upload failed', response.status)
    return result as { id: string }
  }

  async sendTurn(id: string, text: string, revision: number, key: string): Promise<SessionSnapshot> {
    return this.request(`/v1/chat/sessions/${encodeURIComponent(id)}/turns`,
      { text, revision, idempotency_key: key })
  }
}

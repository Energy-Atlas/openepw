import type { AgentEvent, AgentInput, AgentSnapshot, CatalogMap, CatalogScopes, Diagnostics, JobManifest, JobSnapshot, PointAvailability, ViewPage } from './types'

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message)
  }
}

/** One API call, kept for the "Copy log" button of testing deployments. */
export type ApiCall = { time: string; method: string; path: string; status: number | null; ms: number
  body?: string; code?: string; message?: string }

/** Callbacks of a session subscription: events as they happen, the session whenever a turn ends. */
export type SessionHandlers = { event: (event: AgentEvent) => void; state: (state: AgentSnapshot) => void
  error?: () => void }

const MAX_CALLS = 100

export class ChatApi {
  /** The most recent calls, oldest first; read only by the debug log. */
  readonly calls: ApiCall[] = []
  private fetcher: typeof fetch

  constructor(private base = '', fetcher: typeof fetch = (...args) => fetch(...args)) {
    this.fetcher = async (input, init) => {
      const started = Date.now()
      const call: ApiCall = { time: new Date(started).toISOString(), method: init?.method ?? 'GET',
        path: String(input).slice(this.base.length), status: null, ms: 0,
        ...(typeof init?.body === 'string' ? { body: init.body.slice(0, 500) } : {}) }
      this.calls.push(call)
      if (this.calls.length > MAX_CALLS) {
        // Polling fills the list; failures are kept longest.
        const routine = this.calls.findIndex(item => item.status !== null && item.status < 400)
        this.calls.splice(Math.max(routine, 0), 1)
      }
      try {
        const response = await fetcher(input, init)
        call.status = response.status
        if (!response.ok) {
          const detail = await response.clone().json().catch(() => null) as { code?: string; message?: string } | null
          if (detail?.code) call.code = String(detail.code)
          if (detail?.message) call.message = String(detail.message).slice(0, 500)
        }
        return response
      } catch (error) {
        call.message = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        call.ms = Date.now() - started
      }
    }
  }

  /** Server diagnostics; the server answers 404 unless its debug_log setting is on. */
  diagnostics(): Promise<Diagnostics> { return this.request('/v1/diagnostics') }

  private async request<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
    const response = await this.fetcher(`${this.base}${path}`, init ?? (body === undefined ? undefined : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }))
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new ApiError(result.code || 'HTTP_ERROR', result.message || 'Request failed', response.status)
    return result as T
  }

  private session(id: string): string { return `/v2/agent/sessions/${encodeURIComponent(id)}` }

  // The agent chat (/v2/agent) ---------------------------------------------------------------
  create(): Promise<AgentSnapshot> { return this.request('/v2/agent/sessions', {}) }

  get(id: string): Promise<AgentSnapshot> { return this.request(this.session(id)) }

  /** Starts one input; the reply is the session (busy) and the turn's events follow on the subscription. */
  input(id: string, input: AgentInput): Promise<AgentSnapshot> {
    return this.request(`${this.session(id)}/inputs`, input)
  }

  /** An EPW for an open upload form. */
  uploadEpw(id: string, file: File): Promise<AgentSnapshot> {
    const form = new FormData()
    form.append('file', file)
    return this.request(`${this.session(id)}/upload`, undefined, { method: 'POST', body: form })
  }

  /** Events after `after` and the session after each turn: server-sent events where the browser has
   * them (it reconnects with Last-Event-ID), else polling. Returns a function that stops it. */
  subscribe(id: string, after: number, handlers: SessionHandlers): () => void {
    const path = `${this.session(id)}/events`
    if (typeof EventSource !== 'undefined') {
      const source = new EventSource(`${this.base}${path}?after=${after}`, { withCredentials: true })
      source.addEventListener('agent', message => handlers.event(JSON.parse((message as MessageEvent).data)))
      source.addEventListener('state', message => handlers.state(JSON.parse((message as MessageEvent).data)))
      source.onerror = () => handlers.error?.()
      return () => source.close()
    }
    let live = true
    let cursor = after
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      let busy = false
      try {
        const result = await this.request<{ events: AgentEvent[]; cursor: number; state: AgentSnapshot }>(
          `${path}?poll=1&after=${cursor}`)
        if (!live) return
        for (const event of result.events) handlers.event(event)
        cursor = result.cursor
        busy = result.state.busy
        handlers.state(result.state)
      } catch { if (live) handlers.error?.() }
      if (live) timer = setTimeout(poll, busy ? 400 : 1500)
    }
    void poll()
    return () => { live = false; clearTimeout(timer) }
  }

  // Map, jobs, artifacts and charts (REST) ---------------------------------------------------
  catalogScopes(): Promise<CatalogScopes> { return this.request('/v1/catalog/scopes') }
  catalogMap(): Promise<CatalogMap> { return this.request('/v1/catalog/map') }

  pointAvailability(lat: number, lon: number, years: number[] = []): Promise<PointAvailability> {
    const query = new URLSearchParams({ lat: lat.toFixed(2), lon: lon.toFixed(2), years: years.join(',') })
    return this.request(`/v1/catalog/point?${query}`)
  }

  job(id: string): Promise<JobSnapshot> { return this.request(`/v1/jobs/${encodeURIComponent(id)}`) }

  compact(id: string): Promise<{ id: string; path: string }> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/export/compact`, {})
  }

  cancel(id: string): Promise<JobSnapshot> {
    return this.request(`/v1/jobs/${encodeURIComponent(id)}/cancel`, {})
  }

  artifactUrl(id: string): string { return `${this.base}/v1/artifacts/${encodeURIComponent(id)}` }

  manifest(id: string): Promise<JobManifest> { return this.request(this.artifactUrl(id).slice(this.base.length)) }

  prepareView(request: Record<string, unknown>): Promise<{ view_id: string }> {
    return this.request('/v1/views/prepare', request)
  }

  pageView(id: string, offset = 0, limit = 200): Promise<ViewPage> {
    return this.request(`/v1/views/${encodeURIComponent(id)}/page?offset=${offset}&limit=${limit}`)
  }
}

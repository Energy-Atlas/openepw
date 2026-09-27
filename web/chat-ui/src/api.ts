import type { SessionSnapshot } from './types'

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message)
  }
}

export class ChatApi {
  constructor(private base = '', private fetcher: typeof fetch = fetch) {}

  async sendTurn(id: string, text: string, revision: number, key: string): Promise<SessionSnapshot> {
    const response = await this.fetcher(`${this.base}/v1/chat/sessions/${encodeURIComponent(id)}/turns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, revision, idempotency_key: key }),
    })
    const result = await response.json()
    if (!response.ok) {
      throw new ApiError(result.code || 'HTTP_ERROR', result.message || 'Request failed', response.status)
    }
    return result as SessionSnapshot
  }
}

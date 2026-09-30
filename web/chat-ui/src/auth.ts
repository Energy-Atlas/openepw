// Hosted accounts (ADR 0005). A server without accounts (local use) has no /auth routes.

export type AuthSession = { accounts: boolean; signed_in: boolean; email: string | null; domains: string[] }
export type AuthAnswer = { ok: boolean; message: string }

export class AuthApi {
  constructor(private fetcher: typeof fetch = (...args) => fetch(...args)) {}

  async session(): Promise<AuthSession> {
    const response = await this.fetcher('/auth/session')
    if (response.status === 404) return { accounts: false, signed_in: true, email: null, domains: [] }
    if (!response.ok) throw new Error('Account service unavailable')
    return await response.json() as AuthSession
  }

  private async post(path: string, body: Record<string, string> = {}): Promise<AuthAnswer> {
    const response = await this.fetcher(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    let result: Partial<AuthAnswer> = {}
    try { result = await response.json() } catch { /* no body */ }
    return { ok: response.ok, message: result.message || (response.ok ? '' : 'Something went wrong; try again.') }
  }

  login(email: string, password: string) { return this.post('/auth/login', { email, password }) }
  signup(email: string) { return this.post('/auth/signup', { email }) }
  reset(email: string) { return this.post('/auth/reset', { email }) }
  logout() { return this.post('/auth/logout') }
}

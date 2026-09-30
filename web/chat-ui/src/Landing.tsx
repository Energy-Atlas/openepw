import { useEffect, useRef, useState, type FormEvent } from 'react'
import { MapCanvas } from './map/MapCanvas'
import type { AuthApi } from './auth'

type Mode = 'login' | 'signup' | 'reset'

/** Visitors see the globe alone; a click (not a drag) anywhere opens the sign-in window. */
export function Landing({ auth, domains, onSignedIn }: {
  auth: AuthApi; domains: string[]; onSignedIn: () => void
}) {
  const [open, setOpen] = useState(false)
  const pressed = useRef<{ x: number; y: number } | null>(null)
  return <main className="workspace landing"
    onPointerDown={event => { pressed.current = { x: event.clientX, y: event.clientY } }}
    onPointerUp={event => {
      const start = pressed.current
      pressed.current = null
      if (!open && start && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 6) setOpen(true)
    }}>
    <MapCanvas />
    {!open && <button type="button" className="landing-prompt" onClick={() => setOpen(true)}>
      <strong>OpenEPW</strong><span>Sign in or create an account to find weather files</span>
    </button>}
    {open && <AuthDialog auth={auth} domains={domains} onClose={() => setOpen(false)} onSignedIn={onSignedIn} />}
  </main>
}

export function AuthDialog({ auth, domains, onClose, onSignedIn }: {
  auth: AuthApi; domains: string[]; onClose: () => void; onSignedIn: () => void
}) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const domainText = domains.length ? domains.map(domain => `@${domain}`).join(' or ') : 'your work'
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])

  function switchTo(next: Mode) { setMode(next); setNotice(null); setPassword('') }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setNotice(null)
    try {
      const result = mode === 'login' ? await auth.login(email, password)
        : mode === 'signup' ? await auth.signup(email) : await auth.reset(email)
      if (result.ok && mode === 'login') { onSignedIn(); return }
      setNotice({ text: result.message, error: !result.ok })
    } catch {
      setNotice({ text: 'The account service is not answering; try again.', error: true })
    } finally {
      setBusy(false)
    }
  }

  const title = mode === 'login' ? 'Sign in' : mode === 'signup' ? 'Create an account' : 'Reset your password'
  const intro = mode === 'login' ? `Sign in with your ${domainText} email.`
    : mode === 'signup' ? `Use your ${domainText} address. We email a link to choose your password.`
      : 'We email a link to choose a new password.'
  return <div className="auth-backdrop" onPointerDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <form className="auth-dialog" role="dialog" aria-modal="true" aria-label={title} onSubmit={submit}
      onPointerDown={event => event.stopPropagation()} onPointerUp={event => event.stopPropagation()}>
      <div className="auth-head">
        <h2>{title}</h2>
        <button type="button" className="auth-close" aria-label="Close" onClick={onClose}>×</button>
      </div>
      <p className="dialog-note">{intro}</p>
      <label>Email<input type="email" autoComplete={mode === 'login' ? 'username' : 'email'} required autoFocus
        value={email} onChange={event => setEmail(event.target.value)} /></label>
      {mode === 'login' && <label>Password<input type="password" autoComplete="current-password" required
        value={password} onChange={event => setPassword(event.target.value)} /></label>}
      {notice && <p className={notice.error ? 'auth-notice error' : 'auth-notice'} role={notice.error ? 'alert' : 'status'}>
        {notice.text}</p>}
      <button type="submit" className="reply-primary" disabled={busy}>
        {mode === 'login' ? 'Sign in' : 'Send the link'}</button>
      <div className="auth-links">
        {mode !== 'login' && <button type="button" onClick={() => switchTo('login')}>Sign in</button>}
        {mode !== 'signup' && <button type="button" onClick={() => switchTo('signup')}>Create an account</button>}
        {mode === 'login' && <button type="button" onClick={() => switchTo('reset')}>Forgot password</button>}
      </div>
    </form>
  </div>
}

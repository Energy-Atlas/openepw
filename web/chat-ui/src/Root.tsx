import { useEffect, useRef, useState } from 'react'
import { App } from './App'
import { ChatApi } from './api'
import { AuthApi, type AuthSession } from './auth'
import { Landing } from './Landing'

/** Signed-in visitors (or a server without accounts) get the chat; everyone else the landing page. */
export function Root({ auth: suppliedAuth }: { auth?: AuthApi }) {
  const auth = useRef(suppliedAuth ?? new AuthApi()).current
  const [state, setState] = useState<AuthSession | null>(null)
  const [failed, setFailed] = useState(false)
  const [check, setCheck] = useState(0)
  useEffect(() => {
    let live = true
    void auth.session().then(value => { if (live) { setState(value); setFailed(false) } })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [check])
  // The chat's API reports an ended session (expired, signed out elsewhere) back to the landing page.
  const api = useRef(new ChatApi('', async (...args) => {
    const response = await fetch(...args)
    if (response.status === 401) setState(current => current?.accounts ? { ...current, signed_in: false } : current)
    return response
  })).current

  if (failed) return <App api={api} />                 // no account service answer: the chat shows its own error
  if (!state) return <main className="workspace" aria-busy="true" />
  if (state.accounts && !state.signed_in) {
    return <Landing auth={auth} domains={state.domains} onSignedIn={() => setCheck(value => value + 1)} />
  }
  return <App api={api} onSignOut={state.accounts ? async () => {
    await auth.logout().catch(() => undefined)
    setState({ ...state, signed_in: false, email: null })
  } : undefined} />
}

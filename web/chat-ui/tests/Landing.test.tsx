import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthApi, type AuthSession } from '../src/auth'
import { Root } from '../src/Root'

type Call = { path: string; body?: Record<string, string> }

function fakeAuth(sessions: AuthSession[], answers: Record<string, { status: number; message?: string }> = {}) {
  const calls: Call[] = []
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (path === '/auth/session') {
      const next = sessions.length > 1 ? sessions.shift()! : sessions[0]
      return new Response(JSON.stringify(next), { status: 200 })
    }
    const answer = answers[path] ?? { status: 200 }
    return new Response(JSON.stringify({ ok: answer.status === 200, message: answer.message ?? '' }),
      { status: answer.status })
  }) as typeof fetch
  return { auth: new AuthApi(fetcher), calls }
}

const visitor: AuthSession = { accounts: true, signed_in: false, email: null, domains: ['cornell.edu'] }
const member: AuthSession = { accounts: true, signed_in: true, email: 'ada@cornell.edu', domains: ['cornell.edu'] }

beforeEach(() => {
  // jsdom has no PointerEvent; a MouseEvent carries the coordinates the click-versus-drag test needs.
  if (!('PointerEvent' in window)) vi.stubGlobal('PointerEvent', MouseEvent)
  // The chat's own API calls are not under test here; answer them as unavailable.
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })))
  sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('landing page', () => {
  it('shows the globe without the chat, and a click opens the sign-in window', async () => {
    const { auth } = fakeAuth([visitor])
    render(<Root auth={auth} />)
    expect(await screen.findByLabelText('Weather map')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const page = screen.getByRole('main')
    fireEvent.pointerDown(page, { clientX: 100, clientY: 100 })
    fireEvent.pointerUp(page, { clientX: 180, clientY: 140 })                // a drag turns the globe
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.pointerDown(page, { clientX: 100, clientY: 100 })
    fireEvent.pointerUp(page, { clientX: 102, clientY: 101 })                // a click asks to sign in
    expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText('Sign in with your @cornell.edu email.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('signs in, then opens the chat with a sign-out button that returns to the landing page', async () => {
    const { auth, calls } = fakeAuth([visitor, member])
    render(<Root auth={auth} />)
    fireEvent.click(await screen.findByRole('button', { name: /Sign in or create an account/ }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@cornell.edu' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a long enough passphrase' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('textbox', { name: 'Message' })).toBeInTheDocument()
    expect(calls.find(call => call.path === '/auth/login')?.body).toEqual(
      { email: 'ada@cornell.edu', password: 'a long enough passphrase' })
    const signOut = screen.getByRole('button', { name: 'Sign out' })
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument()
    sessionStorage.setItem('openepw-chat-session', 'someone-elses')
    fireEvent.click(signOut)
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument())
    expect(calls.some(call => call.path === '/auth/logout')).toBe(true)
    expect(sessionStorage.getItem('openepw-chat-session')).toBeNull()
    expect(screen.getByRole('button', { name: /Sign in or create an account/ })).toBeInTheDocument()
  })

  it('shows the server answer for a refused sign-in, sign-up and reset', async () => {
    const { auth, calls } = fakeAuth([visitor], {
      '/auth/login': { status: 401, message: 'That email and password do not match an account.' },
      '/auth/signup': { status: 400, message: 'Only @cornell.edu addresses can sign up.' },
      '/auth/reset': { status: 200, message: 'If that address can use OpenEPW, a link is on its way.' },
    })
    render(<Root auth={auth} />)
    fireEvent.click(await screen.findByRole('button', { name: /Sign in or create an account/ }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@cornell.edu' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('do not match an account')

    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(screen.getByRole('dialog', { name: 'Create an account' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()     // the password comes from the link
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@gmail.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send the link' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only @cornell.edu addresses')

    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    fireEvent.click(screen.getByRole('button', { name: 'Forgot password' }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@cornell.edu' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send the link' }))
    expect(await screen.findByText(/a link is on its way/)).toHaveAttribute('role', 'status')
    expect(calls.filter(call => call.path === '/auth/reset')).toHaveLength(1)
  })

  it('goes straight to the chat, without sign-out, when the server has no accounts', async () => {
    const fetcher = (async () => new Response('{"detail":"Not Found"}', { status: 404 })) as typeof fetch
    render(<Root auth={new AuthApi(fetcher)} />)
    expect(await screen.findByRole('textbox', { name: 'Message' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })
})

import { useEffect, useRef, useState, type FormEvent } from 'react'
import './app.css'
import { ChatApi } from './api'
import { MapCanvas } from './map/MapCanvas'
import type { JobSnapshot, SessionSnapshot } from './types'

const sessionKey = 'openepw-chat-session'
let openingSession: Promise<SessionSnapshot> | null = null

function randomKey(): string { return crypto.randomUUID() }

export function App({ api = new ChatApi() }: { api?: ChatApi }) {
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const transcript = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let live = true
    const saved = sessionStorage.getItem(sessionKey)
    const load = saved ? api.get(saved).catch(() => {
      sessionStorage.removeItem(sessionKey)
      return api.create()
    }) : (openingSession ??= api.create().finally(() => { openingSession = null }))
    void load.then(state => {
      if (!live) return
      sessionStorage.setItem(sessionKey, state.id)
      setSession(state)
    }).catch(() => { if (live) setError('Weather service unavailable. Start the local API to chat.') })
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (!session?.job_id) return
    let live = true
    const poll = () => { void api.job(session.job_id!).then(value => {
      if (live) setJob(value)
    }).catch(() => { if (live) setError('Job status could not be refreshed.') }) }
    poll()
    const timer = window.setInterval(poll, 1800)
    return () => { live = false; window.clearInterval(timer) }
  }, [session?.job_id])

  useEffect(() => { transcript.current?.scrollTo?.(0, transcript.current.scrollHeight) }, [session?.events.length])

  async function act(operation: (current: SessionSnapshot) => Promise<SessionSnapshot>) {
    if (!session || busy) return
    setBusy(true); setError('')
    try { setSession(await operation(session)) }
    catch (caught) {
      const error = caught as Error & { code?: string }
      setError(error.code === 'STALE_SESSION' ? 'This choice changed. Refresh the session.' : error.message)
    } finally { setBusy(false) }
  }

  function send(event: FormEvent) {
    event.preventDefault()
    const text = message.trim()
    if (!text) return
    setMessage('')
    void act(current => api.sendTurn(current.id, text, current.revision, randomKey()))
  }

  function download(id: string) {
    const anchor = document.createElement('a')
    anchor.href = api.artifactUrl(id)
    anchor.download = ''
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
  }

  const card = session?.active_card
  const artifacts = job?.bundle?.weather ?? []
  const processed = (job?.completed ?? 0) + (job?.failed ?? 0)

  const selected = session?.facts.location as { id?: string; name?: string; lat: number; lon: number } | undefined
  const candidates = (session?.facts.candidates ?? []) as Array<{ id: string; name?: string; lat: number; lon: number }>

  return <main className="workspace">
    <MapCanvas location={selected} candidates={candidates}
      onPickPoint={point => void act(current => api.setGeography(current.id, current.revision, point, randomKey()))}
      onPickCandidate={id => { if (card?.kind === 'choice') void act(current => api.answer(current.id, card.revision, id, randomKey())) }} />
    <aside className="chat-rail" aria-label="Weather chat">
      <header className="chat-heading">
        <span className="wordmark">OpenEPW</span>
        <span className="chat-subtitle">Weather workspace</span>
      </header>
      <div className="chat-transcript" role="log" aria-live="polite" ref={transcript}>
        <div className="welcome">Where do you need weather?</div>
        <p className="welcome-hint">Name a place and actual years, choose a point on the map, or upload your own EPW.</p>
        {session?.events.map(event => <article key={event.id}
          className={`chat-event ${event.data?.role === 'user' ? 'user-event' : ''}`}>
          {event.type === 'tool' && <span className="event-kind">Tool · {String(event.data?.tool ?? 'service')} · {String(event.data?.phase ?? '')}</span>}
          {event.type === 'message' && <span className="event-kind">{event.data?.role === 'user' ? 'You' : 'Agent'}</span>}
          {event.type === 'plan' && <span className="event-kind">Plan</span>}
          {event.text && <p>{event.text}</p>}
        </article>)}
        {card && <section className="action-card" aria-label="Current question">
          <h2>{card.prompt}</h2>
          {card.kind === 'choice' && <div className="choice-list">
            {card.options?.map(option => <button key={option.id} disabled={busy} type="button"
              onClick={() => void act(current => api.answer(current.id, card.revision, option.id, randomKey()))}>
              {option.label}
            </button>)}
          </div>}
          {card.kind === 'plan_review' && <div>
            {Boolean(session?.facts.location) && <p>Location: {String((session!.facts.location as Record<string, unknown>).name ??
              `${(session!.facts.location as Record<string, unknown>).lat}, ${(session!.facts.location as Record<string, unknown>).lon}`)}</p>}
            {Boolean(session?.facts.geography) && <p>Geography: {Array.isArray(session!.facts.geography) ? `${session!.facts.geography.length} points` : 'area'}</p>}
            <p>Product: {String(session?.facts.product ?? 'unresolved')}{Array.isArray(session?.facts.years) ? ` · ${(session.facts.years as number[]).join(', ')}` : ''}</p>
            {Array.isArray(card.data?.outputs) && <p>{card.data.outputs.length} planned outputs · {String(card.data.plan_hash).slice(0, 12)}…</p>}
            {Array.isArray(card.data?.batch_rows) && (card.data.batch_rows as Array<Record<string, unknown>>).map((row, i) =>
              <p key={i} className="plan-row">{String(row.period_start ?? 'reference')} · {String(row.status)} · {String((row.dataset_selection as Record<string, unknown>)?.provider ?? 'unknown source')}</p>)}
            {Array.isArray(card.data?.warnings) && (card.data.warnings as string[]).map((warning, i) =>
              <p className="warning" key={i}>{warning}</p>)}
            {!card.data?.plan_hash ? <button type="button" disabled={busy}
              onClick={() => void act(current => api.prepare(current.id, current.revision, randomKey()))}>
              Assess and review plan
            </button> : <button type="button" disabled={busy}
              onClick={() => void act(current => api.run(current.id, current.revision, randomKey()))}>
              Run reviewed plan
            </button>}
          </div>}
        </section>}
        {job && <section className="job-card" aria-label="Current weather job">
          <h2>Weather job</h2>
          <p>{job.state} · {processed}/{job.total} outputs · {job.failed} failed</p>
          <progress value={processed} max={Math.max(job.total, 1)} aria-label="Processed outputs" />
          {['queued', 'running'].includes(job.state) && <button type="button" onClick={() => void api.cancel(job.id).then(setJob)}>Cancel job</button>}
          {job.failed > 0 && <button type="button" onClick={() => void api.retry(job.id, randomKey()).then(setJob)}>Retry failed</button>}
          {artifacts.map(item => <div className="artifact-row" key={item.id}>
            <code>{item.id.slice(0, 10)}</code><button type="button" onClick={() => download(item.id)}>Download EPW</button>
          </div>)}
          {artifacts.length > 0 && <button type="button" onClick={() => void api.compact(job.id).then(ref => download(ref.id))}>Download all successful</button>}
        </section>}
        {busy && <p role="status">Working…</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
      <form className="composer" onSubmit={send}>
        <label htmlFor="chat-message">Message</label>
        <div className="composer-row">
          <input id="chat-message" name="message" placeholder="Place, years, and weather type"
            value={message} onChange={event => setMessage(event.target.value)} />
          <button type="submit" disabled={busy || !session}>Send</button>
        </div>
      </form>
    </aside>
  </main>
}

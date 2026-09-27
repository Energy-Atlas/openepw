import { useEffect, useRef, useState, type FormEvent } from 'react'
import './app.css'
import { ChatApi } from './api'
import { MapCanvas } from './map/MapCanvas'
import { geojsonGeography } from './geography'
import { ViewPanel } from './views/ViewPanel'
import type { AvailabilitySummary, JobManifest, JobSnapshot, SessionSnapshot } from './types'

const sessionKey = 'openepw-chat-session'
let openingSession: Promise<SessionSnapshot> | null = null

function randomKey(): string { return crypto.randomUUID() }

export function App({ api: suppliedApi }: { api?: ChatApi }) {
  const api = useRef(suppliedApi ?? new ChatApi()).current
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [manifest, setManifest] = useState<JobManifest | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const acting = useRef(false)
  const [pendingTurns, setPendingTurns] = useState<Array<{ id: string; text: string }>>([])
  const [error, setError] = useState('')
  const [openViews, setOpenViews] = useState<string[]>([])
  const [viewFamily, setViewFamily] = useState('monthly_series')
  const [viewVariable, setViewVariable] = useState('dry_bulb')
  const [viewSelection, setViewSelection] = useState<string[]>([])
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
      setOpenViews((state.view_ids ?? []).slice(-4))
    }).catch(() => { if (live) setError('Weather service unavailable. Start the local API to chat.') })
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (!session?.job_id) return
    setJob(null)
    setManifest(null)
    let live = true
    let timer: number | undefined
    const poll = () => { void api.job(session.job_id!).then(value => {
      if (!live) return
      setJob(value)
      if (['queued', 'running'].includes(value.state)) timer = window.setTimeout(poll, 1800)
    }).catch(() => { if (live) { setError('Job status could not be refreshed.');
      timer = window.setTimeout(poll, 5000) } }) }
    poll()
    return () => { live = false; window.clearTimeout(timer) }
  }, [session?.job_id])

  useEffect(() => {
    if (!job?.bundle?.manifest?.id) return
    let live = true
    void api.manifest(job.bundle.manifest.id).then(value => { if (live) setManifest(value) })
      .catch(() => { if (live) setError('Verified job manifest could not be read.') })
    return () => { live = false }
  }, [job?.bundle?.manifest?.id])

  useEffect(() => { transcript.current?.scrollTo?.(0, transcript.current.scrollHeight) }, [session?.events.length])

  async function act(operation: (current: SessionSnapshot) => Promise<SessionSnapshot>) {
    if (!session || acting.current) return
    acting.current = true
    setBusy(true); setError('')
    try { setSession(await operation(session)) }
    catch (caught) {
      const error = caught as Error & { code?: string }
      setError(error.code === 'STALE_SESSION' ? 'This choice changed. Refresh the session.' : error.message)
    } finally { acting.current = false; setBusy(false) }
  }

  useEffect(() => {
    if (busy || acting.current || !session || !pendingTurns.length) return
    const [next] = pendingTurns
    setPendingTurns(current => current.filter(item => item.id !== next.id))
    void act(current => api.sendTurn(current.id, next.text, current.revision, next.id))
  }, [busy, session?.revision, pendingTurns])

  function send(event: FormEvent) {
    event.preventDefault()
    const text = message.trim()
    if (!text) return
    setMessage('')
    const key = randomKey()
    if (acting.current) {
      setPendingTurns(current => [...current, { id: key, text }])
      return
    }
    if (/\b(?:show|plot|chart|visuali[sz]e|view)\b/i.test(text) && availableIds.length) {
      const family = /\bmonthly\b/i.test(text) ? 'monthly_series'
        : /\bannual|yearly\b/i.test(text) ? 'annual_series'
        : /\bhistogram|distribution\b/i.test(text) ? 'histogram'
        : /\bspatial|map|across locations\b/i.test(text) ? 'spatial' : 'time_series'
      const variable = /\bghi|solar radiation\b/i.test(text) ? 'ghi'
        : /\bwind speed\b/i.test(text) ? 'wind_speed'
        : /\brelative humidity\b/i.test(text) ? 'relative_humidity'
        : 'dry_bulb'
      void prepareView(family, variable, text)
      return
    }
    void act(current => api.sendTurn(current.id, text, current.revision, key))
  }

  async function prepareView(family = viewFamily, variable = viewVariable, prompt?: string) {
    if (!session || busy || !availableIds.length) return
    setBusy(true); setError('')
    try {
      const request = { artifact_ids: viewSelection.length ? viewSelection : availableIds,
        family, variable, allow_partial: true }
      const result = await api.sessionView(session.id, session.revision, randomKey(), request, prompt)
      setSession(result)
      const latest = result.view_ids?.at(-1)
      if (latest) setOpenViews(current => [...new Set([...current, latest])].slice(-4))
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function upload(file: File) {
    if (!session || busy) return
    setBusy(true); setError('')
    try {
      const ref = await api.upload(file)
      setSession(await api.attachUpload(session.id, session.revision, randomKey(), ref.id))
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  async function uploadGeometry(file: File) {
    if (!session || busy) return
    setBusy(true); setError('')
    try {
      if (file.size > 2_000_000) throw new Error('GeoJSON exceeds 2 MB')
      const geography = geojsonGeography(JSON.parse(await file.text()))
      setSession(await api.setGeography(session.id, session.revision, geography, randomKey()))
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
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
  const evidence = card?.data?.availability as AvailabilitySummary | undefined
  const artifacts = job?.bundle?.weather ?? []
  const processed = (job?.completed ?? 0) + (job?.failed ?? 0)
  const uploaded = (session?.facts.uploaded_artifact_ids ?? []) as string[]
  const availableIds = [...artifacts.map(item => item.id), ...uploaded]

  const selected = session?.facts.location as { id?: string; name?: string; lat: number; lon: number } | undefined
  const candidates = (session?.facts.candidates ?? []) as Array<{ id: string; name?: string; lat: number; lon: number }>

  return <main className="workspace">
    <MapCanvas location={selected} candidates={candidates}
      geography={session?.facts.geography as import('./geography').WeatherGeography | undefined}
      resolvedPoints={(session?.facts.resolved_points ?? []) as Array<{lat:number;lon:number}>}
      availability={session?.facts.availability as AvailabilitySummary | undefined}
      onPickPoint={point => void act(current => api.setGeography(current.id, current.revision, point, randomKey()))}
      onPickGeometry={geography => void act(current => api.setGeography(current.id, current.revision, geography, randomKey()))}
      onPickCandidate={id => { if (card?.kind === 'choice') void act(current => api.answer(current.id, card.revision, id, randomKey())) }} />
    <aside className="chat-rail" aria-label="Weather chat">
      <header className="chat-heading">
        <span className="wordmark">OpenEPW</span>
        <span className="chat-subtitle">Weather workspace</span>
        <label className="upload-control">Upload EPW for analysis
          <input type="file" accept=".epw,text/plain" disabled={busy} onChange={event => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
            event.target.value = ''
          }} />
        </label>
        <label className="upload-control">Upload GeoJSON area or points
          <input type="file" accept=".geojson,.json,application/geo+json" disabled={busy} onChange={event => {
            const file = event.target.files?.[0]
            if (file) void uploadGeometry(file)
            event.target.value = ''
          }} />
        </label>
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
            <button type="button" onClick={() => document.getElementById('chat-message')?.focus()}>
              Other — type an answer</button>
          </div>}
          {card.kind === 'plan_review' && <div>
            {Boolean(session?.facts.location) && <p>Location: {String((session!.facts.location as Record<string, unknown>).name ??
              `${(session!.facts.location as Record<string, unknown>).lat}, ${(session!.facts.location as Record<string, unknown>).lon}`)}</p>}
            {Boolean(session?.facts.geography) && <p>Geography: {Array.isArray(session!.facts.geography) ? `${session!.facts.geography.length} points` : 'area'}</p>}
            {Array.isArray(session?.facts.resolved_points) && <details><summary>
              {session.facts.resolved_points.length} service-accepted points (show coordinates)</summary>
              <ol className="point-list">{(session.facts.resolved_points as Array<{lat:number;lon:number}>).map((point, i) =>
                <li key={i}>{point.lat.toFixed(5)}, {point.lon.toFixed(5)}</li>)}</ol></details>}
            <p>Product: {String(session?.facts.product ?? 'unresolved')}{Array.isArray(session?.facts.years) ? ` · ${(session.facts.years as number[]).join(', ')}` : ''}</p>
            {Array.isArray(card.data?.outputs) && <p>{card.data.outputs.length} planned outputs · {String(card.data.plan_hash).slice(0, 12)}…</p>}
            {Array.isArray(card.data?.batch_rows) && (card.data.batch_rows as Array<Record<string, unknown>>).map((row, i) =>
              <p key={i} className="plan-row">{String(row.period_start ?? 'reference')} · {String(row.status)} · {String((row.dataset_selection as Record<string, unknown>)?.provider ?? 'unknown source')}</p>)}
            {Array.isArray(card.data?.warnings) && (card.data.warnings as string[]).map((warning, i) =>
              <p className="warning" key={i}>{warning}</p>)}
            {evidence && <details><summary>Catalog evidence and alternatives</summary>
              <p>Eligibility means the source can be tried; retrieved quality still needs QC.</p>
              <p>Checked {evidence.checked_at}.
                Snapshot: {evidence.snapshots.map(item => item.generation_id).join(', ') || 'bundled contracts'}.</p>
              {evidence.options.map((option, i) => <p className="availability-option" key={i}>
                {option.provider}/{option.dataset} · {option.status} · access {option.access} ·
                {' '}evidence {option.evidence_bases.join(', ') || 'unknown'}
                {option.unknowns.length ? ` · unknown: ${option.unknowns.join('; ')}` : ''}
              </p>)}
            </details>}
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
          {manifest?.batch_rows.map((row, index) => <div className="artifact-row" key={`${row.output_id ?? index}`}>
            <span>Location {row.occurrence_index + 1} · {row.period_start?.slice(0, 4) ?? 'reference'} ·
              {' '}{row.dataset_selection?.provider ?? 'source unknown'} · {row.status}
              {row.issue_codes?.length ? ` (${row.issue_codes.join(', ')})` : ''}</span>
            {row.artifact_id && <button type="button" onClick={() => download(row.artifact_id!)}>Download EPW</button>}
          </div>)}
          {!manifest && artifacts.map(item => <div className="artifact-row" key={item.id}>
            <code>{item.id.slice(0, 10)}</code><button type="button" onClick={() => download(item.id)}>Download EPW</button>
          </div>)}
          {manifest && <p>Simulation ready: {manifest.simulation_ready ? 'yes' : 'no or requires QC review'}</p>}
          {artifacts.length > 0 && <button type="button" onClick={() => void api.compact(job.id).then(ref => download(ref.id))}>Download all successful</button>}
        </section>}
        {availableIds.length > 0 && <section className="view-controls" aria-label="Visualize weather data">
          <h2>View existing weather</h2>
          <label>View type <select value={viewFamily} onChange={event => setViewFamily(event.target.value)}>
            <option value="time_series">Hourly series</option><option value="annual_series">Annual series</option>
            <option value="monthly_series">Monthly series</option><option value="histogram">Distribution</option>
            <option value="spatial">Spatial comparison</option>
          </select></label>
          <label>Variable <select value={viewVariable} onChange={event => setViewVariable(event.target.value)}>
            <option value="dry_bulb">Dry bulb temperature</option><option value="ghi">Global horizontal radiation</option>
            <option value="dni">Direct normal radiation</option><option value="dhi">Diffuse horizontal radiation</option>
            <option value="relative_humidity">Relative humidity</option><option value="wind_speed">Wind speed</option>
          </select></label>
          <fieldset><legend>EPW artifacts</legend>{availableIds.map(id => <label key={id}>
            <input type="checkbox" checked={!viewSelection.length || viewSelection.includes(id)}
              onChange={() => setViewSelection(current => {
                const effective = current.length ? current : availableIds
                const next = effective.includes(id) ? effective.filter(item => item !== id) : [...effective, id]
                return next.length ? next : effective
              })} /> {id.slice(0, 10)}{uploaded.includes(id) ? ' · upload' : ''}
          </label>)}</fieldset>
          <button type="button" disabled={busy} onClick={() => void prepareView()}>Open chart</button>
          {Boolean(session?.view_ids?.length) && <details><summary>Earlier views</summary>
            {(session?.view_ids ?? []).slice(-12).map((id, index) => <button type="button" key={id}
              disabled={openViews.includes(id)} onClick={() =>
                setOpenViews(current => [...current, id].slice(-4))}>
              {openViews.includes(id) ? 'Open' : 'Reopen'} view {index + 1}
            </button>)}
          </details>}
        </section>}
        {busy && <p role="status">Working…</p>}
        {pendingTurns.length > 0 && <section className="pending-turns" aria-label="Waiting messages">
          <h2>Waiting messages</h2>{pendingTurns.map(turn => <div key={turn.id}>
            <span>{turn.text}</span><button type="button" onClick={() =>
              setPendingTurns(current => current.filter(item => item.id !== turn.id))}>Withdraw</button>
          </div>)}
        </section>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
      <form className="composer" onSubmit={send}>
        <label htmlFor="chat-message">Message</label>
        <div className="composer-row">
          <input id="chat-message" name="message" placeholder="Place, years, and weather type"
            value={message} onChange={event => setMessage(event.target.value)} />
          <button type="submit" disabled={!session}>Send</button>
        </div>
      </form>
    </aside>
    {openViews.map((id, index) => <ViewPanel key={id} id={id} index={index} api={api}
      onClose={() => setOpenViews(current => current.filter(item => item !== id))} />)}
  </main>
}

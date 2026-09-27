import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import './app.css'
import { ChatApi } from './api'
import { MapCanvas } from './map/MapCanvas'
import { geojsonGeography } from './geography'
import { mergeJobManifests } from './jobs'
import { ViewPanel } from './views/ViewPanel'
import { transcriptItems } from './transcript'
import type { AvailabilitySummary, CatalogMap, JobManifest, JobSnapshot, SessionSnapshot } from './types'

const sessionKey = 'openepw-chat-session'
// Owner decision 2026-09-27: attachments (+) and map geography input stay hidden for now.
const ATTACH_AND_MAP_INPUT = false
let openingSession: Promise<SessionSnapshot> | null = null

function randomKey(): string { return crypto.randomUUID() }

export function App({ api: suppliedApi }: { api?: ChatApi }) {
  const api = useRef(suppliedApi ?? new ChatApi()).current
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [catalogMap, setCatalogMap] = useState<CatalogMap | null>(null)
  const [sessionAttempt, setSessionAttempt] = useState(0)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [manifest, setManifest] = useState<JobManifest | null>(null)
  const [pastJobs, setPastJobs] = useState<JobSnapshot[]>([])
  const [pastManifests, setPastManifests] = useState<Record<string, JobManifest>>({})
  const [message, setMessage] = useState('')
  const [pickMode, setPickMode] = useState(false)
  const [typing, setTyping] = useState(false)
  const [pendingChoice, setPendingChoice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const acting = useRef(false)
  const [pendingTurns, setPendingTurns] = useState<Array<{ id: string; text: string }>>([])
  const [queuePaused, setQueuePaused] = useState(false)
  const [serverQueue, setServerQueue] = useState<{ queue_id: string; state: string; position: number } | null>(null)
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
      setError('')
      setOpenViews((state.view_ids ?? []).slice(-4))
    }).catch(() => { if (live) setError('Weather service unavailable. Start the local API to chat.') })
    return () => { live = false }
  }, [sessionAttempt])

  useEffect(() => {
    let live = true
    void api.catalogMap().then(value => { if (live) setCatalogMap(value) })
      .catch(() => { if (live) setCatalogMap(null) })
    return () => { live = false }
  }, [api, sessionAttempt])

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

  const historyIds = (session?.job_ids ?? []).filter(id => id !== session?.job_id).join(',')
  useEffect(() => {
    const ids = historyIds ? historyIds.split(',') : []
    if (!ids.length) { setPastJobs([]); setPastManifests({}); return }
    let live = true
    void Promise.all(ids.map(id => api.job(id))).then(values => {
      if (live) setPastJobs(values)
    }).catch(() => { if (live) setError('Earlier retry jobs could not be loaded.') })
    return () => { live = false }
  }, [historyIds])

  useEffect(() => {
    if (!pastJobs.length) return
    let live = true
    void Promise.all(pastJobs.map(async item => item.bundle?.manifest?.id
      ? [item.id, await api.manifest(item.bundle.manifest.id)] as const : null)).then(values => {
      if (live) setPastManifests(Object.fromEntries(values.filter(item => item !== null)))
    }).catch(() => { if (live) setError('Earlier job manifests could not be read.') })
    return () => { live = false }
  }, [pastJobs])

  useEffect(() => { transcript.current?.scrollTo?.(0, transcript.current.scrollHeight) }, [session?.events.length])
  useEffect(() => { setTyping(false); setPendingChoice(null) }, [session?.active_card?.id, session?.active_card?.revision])
  useEffect(() => { if (typing) document.getElementById('chat-message')?.focus() }, [typing])

  async function act(operation: (current: SessionSnapshot) => Promise<SessionSnapshot>,
    callbacks: { success?: () => void; failure?: () => void } = {}) {
    if (!session || acting.current) return
    acting.current = true
    setBusy(true); setError('')
    try { setSession(await operation(session)); callbacks.success?.() }
    catch (caught) {
      const error = caught as Error & { code?: string; snapshot?: SessionSnapshot }
      if (error.code === 'STALE_SESSION' && error.snapshot) setSession(error.snapshot)
      setError(error.code === 'STALE_SESSION' ? 'This choice changed. Refresh the session.' : error.message)
      callbacks.failure?.()
    } finally { acting.current = false; setBusy(false) }
  }

  function submitTurn(current: SessionSnapshot, text: string, key: string) {
    setServerQueue(null)
    return api.sendTurn(current.id, text, current.revision, key, setServerQueue)
      .finally(() => setServerQueue(null))
  }

  useEffect(() => {
    if (busy || acting.current || queuePaused || !session || !pendingTurns.length) return
    const [next] = pendingTurns
    void act(current => submitTurn(current, next.text, next.id), {
      success: () => setPendingTurns(current => current.filter(item => item.id !== next.id)),
      failure: () => setQueuePaused(true),
    })
  }, [busy, session?.revision, pendingTurns, queuePaused])

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
    void act(current => submitTurn(current, text, key))
  }

  async function prepareView(family = viewFamily, variable = viewVariable, prompt?: string) {
    if (!session || busy || !availableIds.length) return
    setBusy(true); setError('')
    try {
      const selectedIds = viewSelection.filter(id => availableIds.includes(id))
      const request = { artifact_ids: selectedIds.length ? selectedIds : availableIds,
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
  // The composer follows the current card: free text only when the session asks for it or the user opts to type.
  const replyMode = !card || card.kind === 'text' || typing || (card.kind === 'map' && !ATTACH_AND_MAP_INPUT)
    ? 'text' : card.kind
  const backLabel = card?.kind === 'choice' ? 'Back to options' : card?.kind === 'plan_review' ? 'Back to review'
    : card?.kind === 'map' ? 'Back to map input' : null
  const visibleEvents = (session?.events ?? []).filter((event, index, events) =>
    !(card && index === events.length - 1 &&
      ((event.type === 'question' && event.text === card.prompt)
        || (event.type === 'plan' && card.kind === 'plan_review'))))
  const evidence = card?.data?.availability as AvailabilitySummary | undefined
  const chain = [...pastJobs.map(item => ({ job: item, manifest: pastManifests[item.id] ?? null })),
    ...(job ? [{ job, manifest }] : [])]
  const mergedJobs = mergeJobManifests(chain)
  const processed = (job?.completed ?? 0) + (job?.failed ?? 0)
  const uploaded = (session?.facts.uploaded_artifact_ids ?? []) as string[]
  const availableIds = [...mergedJobs.artifactIds, ...uploaded]

  const resolvedPoints = (session?.facts.resolved_points ?? []) as Array<{ id?: string; lat: number; lon: number }>
  const selected = (session?.facts.location as { id?: string; name?: string; lat: number; lon: number } | undefined)
    ?? (resolvedPoints.length === 1 ? resolvedPoints[0] : undefined)
  const candidateFacts = (session?.facts.candidates ?? []) as Array<{ id: string; name?: string; lat: number; lon: number }>
  // Location choices are previewed on the map and only answered after an explicit Confirm.
  const locationChoice = card?.kind === 'choice' && candidateFacts.length > 0
  const optionNumber = (id: string) => (card?.options?.findIndex(option => option.id === id) ?? -1) + 1
  const candidates = useMemo(() => candidateFacts.map(candidate => ({ ...candidate,
    number: optionNumber(candidate.id) || undefined,
    name: card?.options?.find(option => option.id === candidate.id)?.label ?? candidate.name })),
  [JSON.stringify(candidateFacts), card?.id, card?.revision])
  const confirmChoice = (id: string) => {
    if (card?.kind === 'choice') void act(current => api.answer(current.id, card.revision, id, randomKey()))
  }
  const coordinatesFor = (row: JobManifest['batch_rows'][number]) => {
    const point = row.metadata?.requested_location
    return point ? ` · ${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}` : ''
  }

  const attachControl = (accept: string) => <label className="attach-control" title="Attach EPW or GeoJSON">
    <span aria-hidden="true">+</span>
    <input type="file" aria-label="Attach EPW or GeoJSON" accept={accept}
      disabled={busy || !session} onChange={event => {
        const file = event.target.files?.[0]
        if (file) {
          if (/\.epw$/i.test(file.name)) void upload(file)
          else if (/\.(geojson|json)$/i.test(file.name)) void uploadGeometry(file)
          else setError('Attach an EPW or GeoJSON file.')
        }
        event.target.value = ''
      }} />
  </label>

  return <main className="workspace">
    <MapCanvas location={selected} candidates={candidates} pickMode={pickMode}
      catalogMap={catalogMap} years={(session?.facts.years ?? []) as number[]}
      onExitPickMode={() => setPickMode(false)}
      geography={session?.facts.geography as import('./geography').WeatherGeography | undefined}
      resolvedPoints={resolvedPoints}
      availability={session?.facts.availability as AvailabilitySummary | undefined}
      onPickPoint={point => void act(current => api.setGeography(current.id, current.revision, point, randomKey()))}
      onPickGeometry={geography => void act(current => api.setGeography(current.id, current.revision, geography, randomKey()))}
      pendingCandidate={locationChoice ? pendingChoice : null} onConfirmCandidate={confirmChoice}
      onClearCandidate={() => setPendingChoice(null)}
      onPickCandidate={id => { if (locationChoice) setPendingChoice(id) }} />
    <aside className="chat-rail" aria-label="Weather chat">
      <div className="chat-transcript" role="log" aria-live="polite" ref={transcript}>
        <article className="chat-event assistant-event welcome">
          <strong>Where do you need weather?</strong>
          <p>Name a place and actual years, choose geography on the map, or attach an EPW.</p>
        </article>
        {transcriptItems(visibleEvents).map(item => item.kind === 'tool'
          ? <div key={item.id} className="tool-line" title={`${item.tool}: ${item.action}${item.result ? ` · ${item.result}` : ''}`}>
            <span className="tool-icon" aria-hidden="true"><ToolIcon /></span>
            <span className="tool-text"><span className="visually-hidden">Tool {item.tool}: </span>{item.action}
              {item.result && <span className="tool-result"> · {item.result}</span>}</span>
          </div>
          : <article key={item.event.id}
            className={`chat-event ${item.event.data?.role === 'user' ? 'user-event' : ''} assistant-event`}>
            {item.event.type === 'message' && <span className="event-kind">{item.event.data?.role === 'user' ? 'You' : 'Agent'}</span>}
            {item.event.type === 'plan' && <span className="event-kind">Plan review</span>}
            {item.event.text && <p>{item.event.text}</p>}
          </article>)}
        {card && <section className="action-card" aria-label="Current question">
          <span className="event-kind">Agent</span>
          <h2>{card.prompt}</h2>
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
          </div>}
        </section>}
        {job && <section className="job-card" aria-label="Current weather job">
          <h2>Weather job</h2>
          <p>{job.state} · {processed}/{job.total} outputs · {job.failed} failed</p>
          <progress value={processed} max={Math.max(job.total, 1)} aria-label="Processed outputs" />
          {['queued', 'running'].includes(job.state) && <button type="button" onClick={() => void api.cancel(job.id).then(setJob)}>Cancel job</button>}
          {job.failed > 0 && <button type="button" disabled={busy} onClick={() =>
            void act(current => api.retrySession(current.id, current.revision, randomKey()))}>Retry failed</button>}
          {!mergedJobs.complete && <p className="warning">Verified output mapping is loading or unavailable; downloads wait for the manifest.</p>}
          {mergedJobs.rows.map((row, index) => <div className="artifact-row" key={`${row.output_id ?? index}`}>
            <span>Location {row.occurrence_index + 1}{coordinatesFor(row)} ·
              {' '}{row.period_start?.slice(0, 4) ?? 'reference'} · {row.dataset_selection?.provider ?? 'source unknown'} · {row.status}
              {row.issue_codes?.length ? ` (${row.issue_codes.join(', ')})` : ''}</span>
            {row.artifact_id && mergedJobs.artifactIds.includes(row.artifact_id) &&
              <button type="button" onClick={() => download(row.artifact_id!)}>Download EPW</button>}
          </div>)}
          {mergedJobs.complete && <p>Simulation ready: {chain.every(item => item.manifest?.simulation_ready) ? 'yes' : 'no or requires QC review'}</p>}
          {mergedJobs.artifactIds.length > 0 && mergedJobs.complete && <button type="button"
            onClick={() => void api.compactSession(session!.id).then(ref => download(ref.id))}>
            Download all successful</button>}
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
        {serverQueue?.state === 'queued' && <section className="pending-turns" aria-label="Server waiting message">
          <p>Waiting on server · position {serverQueue.position}</p>
          <button type="button" onClick={() => void api.withdrawTurn(serverQueue.queue_id)
            .catch(() => setError('Waiting message could not be withdrawn.'))}>Withdraw waiting message</button>
        </section>}
        {pendingTurns.length > 0 && <section className="pending-turns" aria-label="Waiting messages">
          <h2>Waiting messages</h2>{queuePaused && <button type="button" onClick={() =>
            setQueuePaused(false)}>Retry waiting message</button>}{pendingTurns.map(turn => <div key={turn.id}>
            <span>{turn.text}</span><button type="button" onClick={() => {
              setPendingTurns(current => current.filter(item => item.id !== turn.id))
              setQueuePaused(false)
            }}>Withdraw</button>
          </div>)}
        </section>}
        {error && <p className="error" role="alert">{error}</p>}
        {!session && error && <button type="button" onClick={() => setSessionAttempt(value => value + 1)}>
          Reconnect to local service</button>}
      </div>
      <form className="composer" onSubmit={send} aria-label="Reply">
        {replyMode === 'text' ? <>
          <label className="visually-hidden" htmlFor="chat-message">Message</label>
          <div className="composer-row">
            {ATTACH_AND_MAP_INPUT && <>
              {attachControl('.epw,.geojson,.json,text/plain,application/geo+json')}
              <button className="map-input-trigger" type="button" aria-label="Pick geography on map" aria-pressed={pickMode}
                onClick={() => setPickMode(current => !current)}>Map</button>
            </>}
            <input id="chat-message" name="message" placeholder="Place, years, and weather type"
              value={message} onChange={event => setMessage(event.target.value)} />
            <button type="submit" disabled={!session}>{typing && card?.kind === 'choice' ? 'Confirm' : 'Send'}</button>
          </div>
          {typing && backLabel && <button className="reply-alt" type="button" onClick={() => setTyping(false)}>{backLabel}</button>}
        </> : <div className="reply-options" role="group" aria-label="Reply options">
          {card?.kind === 'choice' && <>
            {card.options?.map((option, index) => locationChoice
              ? <button key={option.id} disabled={busy} type="button" className="numbered-option"
                aria-pressed={pendingChoice === option.id} onClick={() => setPendingChoice(option.id)}>
                <span className="option-number" aria-hidden="true">{index + 1}</span>{option.label}</button>
              : <button key={option.id} disabled={busy} type="button" onClick={() => confirmChoice(option.id)}>
                {option.label}</button>)}
            <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Other — type an answer</button>
            {locationChoice && pendingChoice && <button className="reply-primary" type="button" disabled={busy}
              onClick={() => confirmChoice(pendingChoice)}>Confirm</button>}
          </>}
          {card?.kind === 'plan_review' && <>
            {!card.data?.plan_hash ? <button className="reply-primary" type="button" disabled={busy}
              onClick={() => void act(current => api.prepare(current.id, current.revision, randomKey()))}>
              Assess and review plan</button> : <button className="reply-primary" type="button" disabled={busy}
              onClick={() => void act(current => api.run(current.id, current.revision, randomKey()))}>
              Run reviewed plan</button>}
            <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Type a correction</button>
          </>}
          {card?.kind === 'map' && <>
            <button type="button" aria-pressed={pickMode} onClick={() => setPickMode(true)}>Choose on map</button>
            {attachControl('.geojson,.json,application/geo+json')}
            <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Type coordinates</button>
          </>}
        </div>}
      </form>
    </aside>
    {openViews.map((id, index) => <ViewPanel key={id} id={id} index={index} api={api}
      onClose={() => setOpenViews(current => current.filter(item => item !== id))} />)}
  </main>
}

/** Wrench glyph for tool-call lines; the viewBox is cropped square around the path so it centres. */
function ToolIcon() {
  return <svg viewBox="2.08 4.72 16.4 16.4" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.1"
    strokeLinecap="round" strokeLinejoin="round">
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.1L3.6 17.1a1.8 1.8 0 0 0 2.5 2.5l5.7-5.7a4 4 0 0 0 5.1-5.4l-2.4 2.4-2.3-.4-.4-2.3z" />
  </svg>
}

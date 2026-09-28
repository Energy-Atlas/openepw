import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import Markdown from 'react-markdown'
import './app.css'
import { ChatApi } from './api'
import { MapCanvas } from './map/MapCanvas'
import type { ProductAvailability } from './map/availabilityCallouts'
import { ProductDialog } from './ProductDialog'
import { geojsonGeography } from './geography'
import { mergeJobManifests } from './jobs'
import { ViewPanel } from './views/ViewPanel'
import { transcriptItems } from './transcript'
import { BackIcon, DownloadIcon, EnterIcon, RestartIcon, TickIcon, ToolIcon } from './icons'
import type { AvailabilitySummary, CatalogMap, ChatEvent, JobManifest, JobSnapshot, SessionSnapshot } from './types'

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
  // Every job in the session: one per product kind, each with its retries.
  const [jobs, setJobs] = useState<Record<string, JobSnapshot>>({})
  const [manifests, setManifests] = useState<Record<string, JobManifest>>({})
  const [message, setMessage] = useState('')
  const [pickMode, setPickMode] = useState(false)
  const [typing, setTyping] = useState(false)
  const [pendingChoice, setPendingChoice] = useState<string | null>(null)
  // Products ticked in the dialog or clicked on the map, confirmed together.
  const [checkedProducts, setCheckedProducts] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  // Steps of the running action, shown as they start rather than only when it finishes.
  const [liveSteps, setLiveSteps] = useState<ChatEvent[]>([])
  const [confirmReset, setConfirmReset] = useState(false)
  const acting = useRef(false)
  const [pendingTurns, setPendingTurns] = useState<Array<{ id: string; text: string }>>([])
  const [queuePaused, setQueuePaused] = useState(false)
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

  const jobIds = (session?.job_ids?.length ? session.job_ids : session?.job_id ? [session.job_id] : []).join(',')
  useEffect(() => {
    const ids = jobIds ? jobIds.split(',') : []
    if (!ids.length) { setJobs({}); setManifests({}); return }
    let live = true
    let timer: number | undefined
    const poll = () => { void Promise.all(ids.map(id => api.job(id))).then(values => {
      if (!live) return
      setJobs(Object.fromEntries(values.map(value => [value.id, value])))
      if (values.some(value => ['queued', 'running'].includes(value.state))) timer = window.setTimeout(poll, 1800)
    }).catch(() => { if (live) { setError('Job status could not be refreshed.');
      timer = window.setTimeout(poll, 5000) } }) }
    poll()
    return () => { live = false; window.clearTimeout(timer) }
  }, [jobIds])

  const manifestIds = Object.values(jobs).map(item => item.bundle?.manifest?.id ? `${item.id}=${item.bundle.manifest.id}` : '')
    .filter(Boolean).join(',')
  useEffect(() => {
    const wanted = manifestIds ? manifestIds.split(',').map(item => item.split('=') as [string, string]) : []
    const missing = wanted.filter(([id]) => !manifests[id])
    if (!missing.length) return
    let live = true
    void Promise.all(missing.map(async ([id, manifestId]) => [id, await api.manifest(manifestId)] as const))
      .then(values => { if (live) setManifests(current => ({ ...current, ...Object.fromEntries(values) })) })
      .catch(() => { if (live) setError('Verified job manifest could not be read.') })
    return () => { live = false }
  }, [manifestIds])

  useEffect(() => { transcript.current?.scrollTo?.(0, transcript.current.scrollHeight) }, [session?.events.length, liveSteps.length])
  useEffect(() => { setTyping(false); setPendingChoice(null); setCheckedProducts([]) },
    [session?.active_card?.id, session?.active_card?.revision])
  useEffect(() => { if (typing) document.getElementById('chat-message')?.focus() }, [typing])

  useEffect(() => {
    if (!busy || !session?.id || typeof api.progress !== 'function') return
    let live = true
    let timer: number | undefined
    const poll = () => void api.progress(session.id).then(value => { if (live) setLiveSteps(value.steps) })
      .catch(() => undefined).finally(() => { if (live) timer = window.setTimeout(poll, 350) })
    poll()
    return () => { live = false; window.clearTimeout(timer); setLiveSteps([]) }
  }, [busy, session?.id])

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
    return api.sendTurn(current.id, text, current.revision, key)
  }

  function startOver() {
    // A new session; the previous one and its jobs and artifacts stay on the server.
    sessionStorage.removeItem(sessionKey)
    setSession(null); setJobs({}); setManifests({})
    setOpenViews([]); setMessage(''); setPendingTurns([]); setQueuePaused(false)
    setTyping(false); setPendingChoice(null); setError('')
    setSessionAttempt(value => value + 1)
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
  // A location review keeps the input open so the user can steer the location by text.
  const replyMode = !card || card.kind === 'text' || card.kind === 'location_review' || typing
    || (card.kind === 'map' && !ATTACH_AND_MAP_INPUT)
    ? 'text' : card.kind
  const backLabel = card?.kind === 'choice' ? 'Back to options' : card?.kind === 'plan_review' ? 'Back to review'
    : card?.kind === 'map' ? 'Back to map input' : null
  const visibleEvents = (session?.events ?? []).filter((event, index, events) =>
    !(card && index === events.length - 1 &&
      ((event.type === 'question' && event.text === card.prompt)
        || (event.type === 'plan' && card.kind === 'plan_review'))))
  const evidence = card?.data?.availability as AvailabilitySummary | undefined
  const chain = (jobIds ? jobIds.split(',') : []).filter(id => jobs[id])
    .map(id => ({ job: jobs[id], manifest: manifests[id] ?? null }))
  const mergedJobs = mergeJobManifests(chain)
  // The latest job of each group (one group per product kind) gives the progress shown.
  const heads = (session?.job_groups ?? (jobIds ? [jobIds.split(',')] : []))
    .map(group => jobs[group[group.length - 1]]).filter(Boolean)
  const running = heads.filter(item => ['queued', 'running'].includes(item.state))
  const job = heads.length ? { state: running.length ? running[0].state : [...new Set(heads.map(item => item.state))].join(', '),
    total: heads.reduce((sum, item) => sum + item.total, 0), completed: heads.reduce((sum, item) => sum + item.completed, 0),
    failed: heads.reduce((sum, item) => sum + item.failed, 0) } : null
  const processed = (job?.completed ?? 0) + (job?.failed ?? 0)
  const uploaded = (session?.facts.uploaded_artifact_ids ?? []) as string[]
  const availableIds = [...mergedJobs.artifactIds, ...uploaded]

  const resolvedPoints = (session?.facts.resolved_points ?? []) as Array<{ id?: string; lat: number; lon: number }>
  const selected = (session?.facts.location as { id?: string; name?: string; lat: number; lon: number } | undefined)
    ?? (resolvedPoints.length === 1 ? resolvedPoints[0] : undefined)
  const candidateFacts = (session?.facts.candidates ?? []) as Array<{ id: string; name?: string; lat: number; lon: number }>
  // Location choices are previewed on the map and only answered after an explicit Confirm.
  const locationChoice = card?.kind === 'choice' && candidateFacts.length > 0
  // Location and weather-product choices are selected first, then confirmed with the tick beside them.
  const productChoice = card?.kind === 'choice' && card.data?.field === 'product'
  const productAvailability = productChoice ? card.data?.availability as ProductAvailability | undefined : undefined
  // Actual-year and typical-year products may be mixed; each kind becomes its own plan and job.
  const toggleProduct = (id: string) => {
    if (!card?.options?.some(option => option.id === id)) return
    setCheckedProducts(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
  }
  const confirmFirst = locationChoice || productChoice
  const lastEventId = session?.events.at(-1)?.id
  const optionNumber = (id: string) => (card?.options?.findIndex(option => option.id === id) ?? -1) + 1
  const candidates = useMemo(() => candidateFacts.map(candidate => ({ ...candidate,
    number: optionNumber(candidate.id) || undefined,
    name: card?.options?.find(option => option.id === candidate.id)?.label ?? candidate.name })),
  [JSON.stringify(candidateFacts), card?.id, card?.revision])
  const confirmChoice = (id: string) => {
    if (card?.kind === 'choice') void act(current => api.answer(current.id, card.revision, id, randomKey()))
  }
  const jobActive = running.length > 0
  // Start over is always available, outside the chat panel to the left of the reply area; it asks first.
  const resetButton = <button type="button" className="icon-button" aria-label="Start over" title="Start over"
    aria-expanded={confirmReset} disabled={busy} onClick={() => setConfirmReset(value => !value)}><RestartIcon /></button>
  // Jobs of Copernicus CDS products wait in Copernicus's queue, one request per month.
  const queuedJobs = new Set((session?.events ?? []).filter(event => event.type === 'job' && event.data?.queued)
    .map(event => String(event.data?.job_id)))
  const waitingOnQueue = running.some(item => queuedJobs.has(item.id))
  const placeholder = placeholderFor(card ?? null, typing, locationChoice)
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
      productAvailability={productAvailability ?? null} selectedProducts={productChoice ? checkedProducts : []}
      onToggleProduct={productChoice && !busy ? toggleProduct : undefined}
      pointAvailability={(lat, lon) => api.pointAvailability(lat, lon, (session?.facts.years ?? []) as number[])}
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
            {item.event.data?.role !== 'user' && item.event.id !== lastEventId && !busy && <button type="button"
              className="rollback" aria-label="Roll back to here" title="Roll back to here"
              onClick={() => void act(current => api.back(current.id, current.revision, randomKey(), item.event.id))}>
              <BackIcon /></button>}
            {item.event.type === 'message' && <span className="event-kind">{item.event.data?.role === 'user' ? 'You' : 'Agent'}</span>}
            {item.event.type === 'plan' && <span className="event-kind">Plan review</span>}
            {item.event.text && (item.event.data?.role === 'user' && !item.event.data?.choice ? <p>{item.event.text}</p>
              : <div className="md"><Markdown>{item.event.text}</Markdown></div>)}
          </article>)}
        {busy && transcriptItems(liveSteps).map(item => item.kind === 'tool' && <div key={`live-${item.id}`}
          className="tool-line live" role="status" aria-label={`Running: ${item.action}`}>
          <span className="tool-icon" aria-hidden="true"><ToolIcon /></span>
          <span className="tool-text">{item.action}{item.result && <span className="tool-result"> · {item.result}</span>}
            <span className="live-dots" aria-hidden="true" /></span>
        </div>)}
        {job && <section className="job-card" aria-label="Current weather job">
          <h2>{heads.length > 1 ? `Weather jobs (${heads.length})` : 'Weather job'}</h2>
          <p>{job.state} · {processed}/{job.total} outputs · {job.failed} failed</p>
          <progress value={processed} max={Math.max(job.total, 1)} aria-label="Processed outputs" />
          {running.length > 0 && <button type="button" onClick={() => void Promise.all(running.map(item => api.cancel(item.id)))
            .then(values => setJobs(current => ({ ...current, ...Object.fromEntries(values.map(value => [value.id, value])) })))}>
            Cancel job</button>}
          {job.failed > 0 && <button type="button" disabled={busy} onClick={() =>
            void act(current => api.retrySession(current.id, current.revision, randomKey()))}>Retry failed</button>}
          {waitingOnQueue && <p className="card-note">Copernicus CDS requests wait in the Copernicus queue, one month
            per request, so several years can take hours. The other products run alongside and finish first.</p>}
          {running.length > 0 && heads.length > 1 ? <p className="card-note">Finished outputs can be downloaded now; the
            full ZIP waits for every job.</p>
            : !mergedJobs.complete && <p className="warning">Verified output mapping is loading or unavailable; downloads wait for the manifest.</p>}
          {mergedJobs.rows.map((row, index) => <div className="artifact-row" key={`${row.output_id ?? index}`}>
            <span>Location {row.occurrence_index + 1}{coordinatesFor(row)} ·
              {' '}{row.period_start?.slice(0, 4) ?? 'reference'} · {row.dataset_selection?.provider ?? 'source unknown'} · {row.status}
              {row.issue_codes?.length ? ` (${row.issue_codes.join(', ')})` : ''}</span>
            {row.artifact_id && mergedJobs.artifactIds.includes(row.artifact_id) &&
              <button type="button" className="icon-button" aria-label="Download EPW" title="Download EPW"
                onClick={() => download(row.artifact_id!)}><DownloadIcon /></button>}
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
        {pendingTurns.length > 0 && <section className="pending-turns" aria-label="Waiting messages">
          <h2>Waiting messages</h2>{queuePaused && <button type="button" onClick={() =>
            setQueuePaused(false)}>Retry waiting message</button>}{pendingTurns.map(turn => <div key={turn.id}>
            <span>{turn.text}</span><button type="button" onClick={() => {
              setPendingTurns(current => current.filter(item => item.id !== turn.id))
              setQueuePaused(false)
            }}>Withdraw</button>
          </div>)}
        </section>}
      </div>
      <div className="chat-dock">
      {card && <section className="action-card" aria-label="Current question">
        <span className="event-kind">Agent</span>
        <h2>{card.prompt}</h2>
        {productAvailability && productAvailability.locations.length > 0 && <p className="card-note">
          Map tags show availability{productAvailability.years_assumed
            ? ` for ${productAvailability.years.join(', ')}; you choose the years next`
            : ` for ${productAvailability.years.join(', ')}`}. Solid tags are listed in the catalog; outlined
          tags with ? are checked when planning. Click a tag to select or deselect its product.{productAvailability.omitted_locations > 0
            ? ` Tags cover the first ${productAvailability.locations.length} places.` : ''}</p>}
        {card.kind === 'location_review' && typeof card.data?.summary === 'string' &&
          <div className="md"><Markdown>{card.data.summary}</Markdown></div>}
        {card.kind === 'plan_review' && <div>
          {Boolean(session?.facts.location) && <p>Location: {String((session!.facts.location as Record<string, unknown>).name ??
            `${(session!.facts.location as Record<string, unknown>).lat}, ${(session!.facts.location as Record<string, unknown>).lon}`)}</p>}
          {Boolean(session?.facts.geography) && <p>Geography: {Array.isArray(session!.facts.geography) ? `${session!.facts.geography.length} points` : 'area'}</p>}
          {Array.isArray(session?.facts.resolved_points) && <details><summary>
            {session.facts.resolved_points.length} service-accepted points (show coordinates)</summary>
            <ol className="point-list">{(session.facts.resolved_points as Array<{lat:number;lon:number}>).map((point, i) =>
              <li key={i}>{point.lat.toFixed(5)}, {point.lon.toFixed(5)}</li>)}</ol></details>}
          <p>Product: {Array.isArray(session?.facts.product_labels) ? (session.facts.product_labels as string[]).join('; ')
            : String(session?.facts.product ?? 'unresolved')}{Array.isArray(session?.facts.years) ? ` · ${(session.facts.years as number[]).join(', ')}` : ''}</p>
          {Array.isArray(card.data?.outputs) && <p>{card.data.outputs.length} planned outputs · {String(card.data.plan_hash).slice(0, 12)}…</p>}
          {typeof card.data?.summary === 'string' ? <div className="md"><Markdown>{card.data.summary}</Markdown></div>
            : Array.isArray(card.data?.batch_rows) && (card.data.batch_rows as Array<Record<string, unknown>>).map((row, i) =>
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
        {error && <p className="error" role="alert">{error}</p>}
        {!session && error && <button type="button" onClick={() => setSessionAttempt(value => value + 1)}>
          Reconnect to local service</button>}
        {busy && !liveSteps.length && <p className="dock-status" role="status" aria-label="Working">Working…</p>}
        {(busy && replyMode !== 'text') || (jobActive && !card) ? null : <>
    <form className="composer" onSubmit={send} aria-label="Reply">
      {replyMode === 'text' ? <>
        {card?.kind === 'location_review' && <button className="reply-primary approve-location" type="button"
          disabled={busy} onClick={() => void act(current => api.approveLocation(current.id, current.revision, randomKey()))}>
          <TickIcon />{card.data?.several ? 'Approve locations' : 'Approve location'}</button>}
        <label className="visually-hidden" htmlFor="chat-message">Message</label>
        <div className="composer-row">
          {ATTACH_AND_MAP_INPUT && <>
            {attachControl('.epw,.geojson,.json,text/plain,application/geo+json')}
            <button className="map-input-trigger" type="button" aria-label="Pick geography on map" aria-pressed={pickMode}
              onClick={() => setPickMode(current => !current)}>Map</button>
          </>}
          <input id="chat-message" name="message" placeholder={placeholder}
            value={message} onChange={event => setMessage(event.target.value)} />
          {typing && card?.kind === 'choice'
            ? <button type="submit" className="icon-submit" aria-label="Confirm" title="Confirm" disabled={!session}><TickIcon /></button>
            : <button type="submit" className="icon-submit" aria-label="Send" title="Send" disabled={!session}><EnterIcon /></button>}
        </div>
        {typing && backLabel && <button className="reply-alt" type="button" onClick={() => setTyping(false)}>{backLabel}</button>}
      </> : productChoice ? <ProductDialog options={card.options ?? []} selected={checkedProducts}
        busy={busy} onToggle={toggleProduct} onType={() => setTyping(true)}
        onConfirm={() => void act(current => api.chooseProducts(current.id, card.revision, checkedProducts, randomKey()))} />
      : <div className="reply-options" role="group" aria-label="Reply options">
        {card?.kind === 'choice' && <>
          {card.options?.map((option, index) => confirmFirst
            ? <Fragment key={option.id}>{productChoice && option.group && option.group !== card.options?.[index - 1]?.group
              && <span className="option-group">{option.group === 'actual' ? 'Actual year' : 'Typical year'}</span>}
              <span className="option-row">
              <button disabled={busy} type="button" className={locationChoice ? 'numbered-option' : undefined}
                aria-pressed={pendingChoice === option.id} onClick={() => setPendingChoice(option.id)}>
                {locationChoice && <span className="option-number" aria-hidden="true">{index + 1}</span>}
                {option.label}{option.detail && <span className="option-detail">{option.detail}</span>}</button>
              {pendingChoice === option.id && <button className="option-tick" type="button" disabled={busy}
                aria-label="Confirm" title="Confirm" onClick={() => confirmChoice(option.id)}><TickIcon /></button>}
            </span></Fragment>
            : <button key={option.id} disabled={busy} type="button" onClick={() => confirmChoice(option.id)}>
              {option.label}{option.detail && <span className="option-detail">{option.detail}</span>}</button>)}
          <button className="reply-alt" type="button" onClick={() => setTyping(true)}>Other — type an answer</button>
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
        </>}
        <div className="dock-reset">
          {resetButton}
          {confirmReset && <div className="reset-confirm" role="alertdialog" aria-label="Start over?">
            <strong>Start over?</strong>
            <span>This starts a new conversation.</span>
            <div>
              <button type="button" className="reply-alt" onClick={() => setConfirmReset(false)}>Cancel</button>
              <button type="button" className="reply-primary" autoFocus
                onClick={() => { setConfirmReset(false); startOver() }}>Start over</button>
            </div>
          </div>}
        </div>
      </div>
    </aside>
    {openViews.map((id, index) => <ViewPanel key={id} id={id} index={index} api={api}
      onClose={() => setOpenViews(current => current.filter(item => item !== id))} />)}
  </main>
}

function placeholderFor(card: SessionSnapshot['active_card'], typing: boolean, locationChoice: boolean): string {
  if (!card) return 'Place, years, and weather type'
  if (card.kind === 'plan_review') return 'Describe what to change'
  if (card.kind === 'location_review') return card.data?.several ? 'Or edit the list, e.g. remove 3' : 'Or describe a correction'
  if (card.kind === 'text') return /year/i.test(card.prompt) ? 'e.g. 2018 or 2016–2018'
    : /where/i.test(card.prompt) ? 'Place, coordinates, or a list of places' : 'Type your answer'
  if (card.kind === 'choice' && typing) {
    const field = (card.data as { field?: string } | undefined)?.field
    return field === 'region' ? 'Country, state or province' : field === 'definition' ? 'Minimum population, e.g. 100000'
      : field === 'limit' ? 'How many, e.g. 25' : locationChoice ? 'Another place name or coordinates' : 'Type another answer'
  }
  return 'Type your answer'
}

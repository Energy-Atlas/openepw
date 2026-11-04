import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import './app.css'
import { ApiError, ChatApi } from './api'
import { FormDock, type AnswerFields } from './FormDock'
import { MapCanvas } from './map/MapCanvas'
import type { ProductAvailability } from './map/availabilityCallouts'
import { ModelText } from './ModelText'
import { mergeJobManifests } from './jobs'
import { ViewPanel } from './views/ViewPanel'
import { transcriptItems } from './transcript'
import { CopyLogIcon, DownloadIcon, RestartIcon, ToolIcon } from './icons'
import { copyOrSave, debugLogText } from './debugLog'
import type { AgentEvent, AgentInput, AgentSnapshot, CatalogMap, JobManifest, JobSnapshot, OfferedFile } from './types'

// A new key: chats saved through the old /v1 routes are left as they are (owner, 2026-11-01).
export const sessionKey = 'openepw-agent-session'
let openingSession: Promise<AgentSnapshot> | null = null

const REFUSALS: Record<string, string> = {
  SESSION_BUSY: 'The previous step is still being handled.',
}

export function App({ api: suppliedApi }: { api?: ChatApi }) {
  const api = useRef(suppliedApi ?? new ChatApi()).current
  const [session, setSession] = useState<AgentSnapshot | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [sessionAttempt, setSessionAttempt] = useState(0)
  const [catalogMap, setCatalogMap] = useState<CatalogMap | null>(null)
  const [jobs, setJobs] = useState<Record<string, JobSnapshot>>({})
  const [manifests, setManifests] = useState<Record<string, JobManifest>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  // A place picked before Confirm, and products ticked in the dialog or clicked on the map; both
  // belong to the form they were picked on, so a new form starts from its own preselection.
  const [pending, setPending] = useState<{ form: string; id: string } | null>(null)
  const [picks, setPicks] = useState<{ form: string; ids: string[] } | null>(null)
  const [openViews, setOpenViews] = useState<string[]>([])
  const [viewFamily, setViewFamily] = useState('monthly_series')
  const [viewVariable, setViewVariable] = useState('dry_bulb')
  const [confirmReset, setConfirmReset] = useState(false)
  // Testing deployments (server debug_log on) show a "Copy log" button.
  const [debugLog, setDebugLog] = useState(false)
  const [logStatus, setLogStatus] = useState('')
  const cursor = useRef(0)
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
      cursor.current = state.cursor
      setEvents(state.events)
      setSession(state)
      setError('')
    }).catch((caught: ApiError) => {
      if (live) setError(caught?.code === 'SESSION_LIMIT' ? caught.message : 'Weather service unavailable. Start the local API to chat.')
    })
    return () => { live = false }
  }, [sessionAttempt])

  // Events as they happen and the session after each turn.
  useEffect(() => {
    if (!session?.id || typeof api.subscribe !== 'function') return
    return api.subscribe(session.id, cursor.current, {
      event: event => {
        if (event.seq <= cursor.current) return
        cursor.current = event.seq
        setEvents(current => [...current, event])
        const view = event.type === 'view' ? String(event.data?.view_id ?? '') : ''
        if (view) setOpenViews(current => [...new Set([...current, view])].slice(-4))
      },
      state: state => setSession(current => current && current.id === state.id ? { ...state, events: [] } : current),
    })
  }, [session?.id])

  useEffect(() => {
    let live = true
    if (typeof api.diagnostics === 'function')
      void api.diagnostics().then(() => { if (live) setDebugLog(true) }).catch(() => undefined)
    return () => { live = false }
  }, [])

  useEffect(() => {
    let live = true
    void api.catalogMap().then(value => { if (live) setCatalogMap(value) })
      .catch(() => { if (live) setCatalogMap(null) })
    return () => { live = false }
  }, [api, sessionAttempt])

  const jobIds = (session?.job_ids ?? []).join(',')
  useEffect(() => {
    const ids = jobIds ? jobIds.split(',') : []
    if (!ids.length) { setJobs({}); return }
    let live = true
    let timer: number | undefined
    const poll = () => { void Promise.all(ids.map(id => api.job(id))).then(values => {
      if (!live) return
      setJobs(Object.fromEntries(values.map(value => [value.id, value])))
      if (values.some(value => ['queued', 'running'].includes(value.state))) timer = window.setTimeout(poll, 1800)
    }).catch(() => { if (live) { setError('Job status could not be refreshed.'); timer = window.setTimeout(poll, 5000) } }) }
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

  const form = session?.form ?? null
  const formKey = form ? `${form.id}:${form.revision}` : ''
  const pendingChoice = pending?.form === formKey ? pending.id : null
  const setPendingChoice = (id: string | null) => setPending(id === null ? null : { form: formKey, id })
  const checked = picks?.form === formKey ? picks.ids
    : form?.kind === 'product_choice' ? ((form.data?.selected as string[] | undefined) ?? []) : []
  // The newest message stays in view: before each paint, so a dock that grows or shrinks (a form
  // opening, "Working…") never shows the transcript jumping. Scrolling up to read stops it.
  const pinned = useRef(true)
  useLayoutEffect(() => {
    const log = transcript.current
    if (log && pinned.current && log.scrollHeight - log.clientHeight - log.scrollTop > 1)
      log.scrollTo?.(0, log.scrollHeight)
  })
  // A new request leaves the results: their charts and the "View existing weather" card close.
  const stage = session?.stage
  useEffect(() => { if (stage === 'request') setOpenViews([]) }, [stage])

  const busy = sending || Boolean(session?.busy)

  async function send(input: AgentInput) {
    if (!session || busy) return
    setSending(true); setError('')
    try {
      const state = await api.input(session.id, input)
      setSession(current => current ? { ...state, events: [] } : current)
    } catch (caught) {
      const refusal = caught as ApiError
      setError(REFUSALS[refusal.code] ?? refusal.message ?? 'That could not be sent.')
    } finally { setSending(false) }
  }

  function answer(fields: AnswerFields) {
    if (form) void send({ type: 'answer', answer: { interaction_id: form.id, revision: form.revision, ...fields } })
  }

  async function upload(file: File) {
    if (!session || busy) return
    setSending(true); setError('')
    try { setSession(await api.uploadEpw(session.id, file).then(state => ({ ...state, events: [] }))) }
    catch (caught) { setError((caught as Error).message) }
    finally { setSending(false) }
  }

  function startOver() {
    // A new session; the previous one and its jobs and artifacts stay on the server.
    sessionStorage.removeItem(sessionKey)
    setSession(null); setEvents([]); setJobs({}); setManifests({}); setOpenViews([]); setError('')
    cursor.current = 0
    setSessionAttempt(value => value + 1)
  }

  async function openChart() {
    if (!availableIds.length || busy) return
    setError('')
    try {
      const view = await api.prepareView({ artifact_ids: availableIds.slice(-100), family: viewFamily,
        variable: viewVariable, allow_partial: true })
      setOpenViews(current => [...new Set([...current, view.view_id])].slice(-4))
    } catch (caught) { setError((caught as Error).message) }
  }

  function download(id: string) {
    const anchor = document.createElement('a')
    anchor.href = api.artifactUrl(id)
    anchor.download = ''
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
  }

  const chain = (jobIds ? jobIds.split(',') : []).filter(id => jobs[id]).map(id => ({ job: jobs[id], manifest: manifests[id] ?? null }))
  const mergedJobs = mergeJobManifests(chain)
  const heads = chain.map(item => item.job)
  const running = heads.filter(item => ['queued', 'running'].includes(item.state))
  // After a retry the merged manifest rows count each output once (a retry's success replaces the failure).
  const settled = !running.length && heads.length > 1 && mergedJobs.complete
  const job = heads.length ? { state: running.length ? running[0].state : [...new Set(heads.map(item => item.state))].join(', '),
    total: settled ? mergedJobs.rows.length : heads.reduce((sum, item) => sum + item.total, 0),
    completed: settled ? mergedJobs.rows.filter(row => row.status === 'succeeded').length
      : heads.reduce((sum, item) => sum + item.completed, 0),
    failed: settled ? mergedJobs.rows.filter(row => ['failed', 'cancelled'].includes(row.status)).length
      : heads.reduce((sum, item) => sum + item.failed, 0) } : null
  const processed = (job?.completed ?? 0) + (job?.failed ?? 0)
  const availableIds = session?.artifact_ids ?? []
  const viewIds = [...new Set(events.filter(event => event.type === 'view').map(event => String(event.data?.view_id ?? '')))]
    .filter(Boolean)

  const places = session?.places ?? []
  const productChoice = form?.kind === 'product_choice'
  const productAvailability = productChoice ? form?.data?.availability as ProductAvailability | undefined : undefined
  const offered = new Set((form?.options ?? []).map(option => option.id))
  const toggleProduct = (id: string) => {
    if (!offered.has(id)) return
    setPicks({ form: formKey, ids: checked.includes(id) ? checked.filter(item => item !== id) : [...checked, id] })
  }
  const candidates = useMemo(() => (session?.candidates ?? []).map((candidate, index) => ({ ...candidate,
    name: candidate.name ?? undefined, number: index + 1 })), [JSON.stringify(session?.candidates ?? [])])
  const locationChoice = form?.kind === 'choice' && candidates.length > 0

  const copyLog = async () => {
    const server = await api.diagnostics().catch(() => null)
    const text = debugLogText(session ? { ...session, events } : null, api.calls ?? [], server)
    const done = await copyOrSave(text, `openepw-log-${session?.id.slice(0, 8) ?? 'none'}.txt`)
    setLogStatus(done === 'copied' ? 'Log copied' : 'Log saved as a file')
    window.setTimeout(() => setLogStatus(''), 4000)
  }
  const modeLocked = !session?.model_available || session.downgraded
  const otherMode = session?.mode === 'agent' ? 'guided' : 'agent'

  return <main className="workspace">
    <MapCanvas location={places.length === 1 ? { ...places[0], name: places[0].name ?? undefined } : null}
      resolvedPoints={places.length > 1 ? places.map(place => ({ ...place, name: place.name ?? undefined })) : []}
      candidates={candidates} catalogMap={catalogMap} years={session?.years ?? []}
      pendingCandidate={locationChoice ? pendingChoice : null}
      onPickCandidate={id => { if (locationChoice) setPendingChoice(id) }}
      onConfirmCandidate={id => { if (locationChoice) answer({ choice_ids: [id] }) }}
      productAvailability={productAvailability ?? null} selectedProducts={productChoice ? checked : []}
      onToggleProduct={productChoice && !busy ? toggleProduct : undefined}
      pointAvailability={(lat, lon) => api.pointAvailability(lat, lon, session?.years ?? [])} />
    <aside className="chat-rail" aria-label="Weather chat">
      {session && <header className="chat-header">
        <button type="button" className="mode-toggle" aria-pressed={session.mode === 'agent'} disabled={busy || modeLocked || session.ended}
          title={!session.model_available ? 'Agent mode needs a configured model' : session.downgraded
            ? 'This session stays in guided mode after its strike limit' : `Switch to ${otherMode} mode`}
          onClick={() => void send({ type: 'mode', mode: otherMode })}>
          {session.mode === 'agent' ? 'Agent mode' : 'Guided mode'}</button>
        <button type="button" className="reply-alt" disabled={busy || session.ended}
          onClick={() => void send({ type: 'request' })}>Your request</button>
        <button type="button" className="reply-alt" disabled={busy || session.ended}
          onClick={() => void send({ type: 'back' })}>Back</button>
      </header>}
      <div className="chat-transcript" role="log" aria-live="polite" ref={transcript} onScroll={event => {
        const log = event.currentTarget
        pinned.current = log.scrollHeight - log.clientHeight - log.scrollTop < 24
      }}>
        <article className="chat-event assistant-event welcome">
          <strong>Weather files for building simulation</strong>
          <p>Name a place and actual years, or ask what is available. You review the location, products and
            plan before anything runs.</p>
        </article>
        {transcriptItems(events).map(item => item.kind === 'tool'
          ? <div key={item.id} className="tool-line" title={`${item.tool}${item.result ? ` · ${item.result}` : ''}`}>
            <span className="tool-icon" aria-hidden="true"><ToolIcon /></span>
            <span className="tool-text"><span className="visually-hidden">Tool {item.tool}: </span>{item.action}
              {item.result && <span className="tool-result"> · {item.result}</span>}</span>
          </div>
          : <article key={item.event.seq} className={`chat-event ${eventClass(item.event)}`}>
            {item.event.type === 'user' ? <><span className="event-kind">You</span><p>{item.event.text}</p></>
              : item.event.type === 'job' ? <p className="job-line">{item.event.text}</p>
              : item.event.type === 'download' ? <DownloadOffer files={(item.event.data?.files as OfferedFile[] | undefined) ?? []}
                url={id => api.artifactUrl(id)} />
              : <>{item.event.type === 'assistant' && <span className="event-kind">{eventLabel(item.event)}</span>}
                <ModelText text={item.event.text} /></>}
          </article>)}
        {job && <section className="job-card" aria-label="Current weather job">
          <h2>{heads.length > 1 ? `Weather jobs (${heads.length})` : 'Weather job'}</h2>
          <p>{job.state} · {processed}/{job.total} outputs · {job.failed} failed</p>
          <progress value={processed} max={Math.max(job.total, 1)} aria-label="Processed outputs" />
          {running.length > 0 && <button type="button" onClick={() => void Promise.all(running.map(item => api.cancel(item.id)))
            .then(values => setJobs(current => ({ ...current, ...Object.fromEntries(values.map(value => [value.id, value])) })))}>
            Cancel job</button>}
          {running.length > 0 && heads.length > 1 && <p className="card-note">Finished outputs can be downloaded now.</p>}
          {!running.length && !mergedJobs.complete && <p className="warning">Verified output mapping is loading or unavailable; downloads wait for the manifest.</p>}
          {mergedJobs.rows.map((row, index) => <div className="artifact-row" key={`${row.output_id ?? index}`}>
            <span>Location {row.occurrence_index + 1} · {row.period_start?.slice(0, 4) ?? 'reference'} ·
              {' '}{row.dataset_selection?.provider ?? 'source unknown'} · {row.status}
              {row.issue_codes?.length ? ` (${row.issue_codes.join(', ')})` : ''}</span>
            {row.artifact_id && mergedJobs.artifactIds.includes(row.artifact_id) &&
              <button type="button" className="icon-button" aria-label="Download EPW" title="Download EPW"
                onClick={() => download(row.artifact_id!)}><DownloadIcon /></button>}
          </div>)}
          {mergedJobs.complete && <p>Simulation ready: {chain.every(item => item.manifest?.simulation_ready) ? 'yes' : 'no or requires QC review'}</p>}
          {mergedJobs.artifactIds.length > 0 && mergedJobs.complete && <button type="button"
            onClick={() => void Promise.all(heads.filter(item => item.completed > 0).map(item => api.compact(item.id)))
              .then(refs => refs.forEach(ref => download(ref.id))).catch(caught => setError((caught as Error).message))}>
            Download all successful</button>}
        </section>}
        {availableIds.length > 0 && stage !== 'request' && <section className="view-controls" aria-label="Visualize weather data">
          <h2>View existing weather</h2>
          <label>View type <select value={viewFamily} onChange={event => setViewFamily(event.target.value)}>
            <option value="time_series">Hourly series</option><option value="annual_series">Annual series</option>
            <option value="monthly_series">Monthly series</option><option value="histogram">Distribution</option>
            <option value="month_of_year_profile">Month-of-year profile</option><option value="spatial">Spatial comparison</option>
          </select></label>
          <label>Variable <select value={viewVariable} onChange={event => setViewVariable(event.target.value)}>
            <option value="dry_bulb">Dry bulb temperature</option><option value="ghi">Global horizontal radiation</option>
            <option value="dni">Direct normal radiation</option><option value="dhi">Diffuse horizontal radiation</option>
            <option value="relative_humidity">Relative humidity</option><option value="wind_speed">Wind speed</option>
          </select></label>
          <button type="button" disabled={busy} onClick={() => void openChart()}>Open chart</button>
          {viewIds.length > 0 && <details><summary>Earlier charts</summary>
            {viewIds.slice(-12).map((id, index) => <button type="button" key={id} disabled={openViews.includes(id)}
              onClick={() => setOpenViews(current => [...current, id].slice(-4))}>
              {openViews.includes(id) ? 'Open' : 'Reopen'} chart {index + 1}</button>)}
          </details>}
        </section>}
      </div>
      <div className="chat-dock">
        {session && <FormDock snapshot={session} busy={busy} checked={checked} pendingChoice={pendingChoice}
          onPendingChoice={setPendingChoice} onToggleProduct={toggleProduct} onAnswer={answer}
          onText={text => void send({ type: 'text', text })} onUpload={file => void upload(file)} />}
        {!session && <form className="composer" aria-label="Reply" onSubmit={event => event.preventDefault()}>
          <label className="visually-hidden" htmlFor="chat-message">Message</label>
          <div className="composer-row">
            <input id="chat-message" name="message" placeholder="Connecting to the weather service…" disabled />
          </div>
        </form>}
        {session?.ended && <p className="warning" role="status">This session has ended. Start over to continue.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {!session && error && <button type="button" onClick={() => setSessionAttempt(value => value + 1)}>
          Reconnect to local service</button>}
        <div className="dock-reset">
          {debugLog && <button type="button" className="icon-button" aria-label="Copy log"
            title={logStatus || 'Copy log for a bug report'} onClick={() => void copyLog()}><CopyLogIcon /></button>}
          <button type="button" className="icon-button" aria-label="Start over" title="Start over"
            aria-expanded={confirmReset} disabled={sending} onClick={() => setConfirmReset(value => !value)}><RestartIcon /></button>
          {logStatus && <span className="log-status" role="status">{logStatus}</span>}
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

/** A download offer: one link per file; the browser saves it to the person's disk. */
function DownloadOffer({ files, url }: { files: OfferedFile[]; url: (id: string) => string }) {
  return <>
    <span className="event-kind">Agent · download</span>
    <p>{files.length === 1 ? 'Ready to download:' : `Ready to download (${files.length} files):`}</p>
    <ul className="download-list">
      {files.map(file => <li key={file.artifact_id}>
        <a href={url(file.artifact_id)} download={file.filename ?? ''}>{file.number ? `${file.number}. ` : ''}{file.label}</a>
        {file.bytes ? <span className="download-size"> · {(file.bytes / 1e6).toFixed(1)} MB</span> : null}
      </li>)}
    </ul>
  </>
}

function eventClass(event: AgentEvent): string {
  if (event.type === 'user') return 'user-event'
  if (event.type === 'error') return 'assistant-event error-event'
  if (event.type === 'notice') return 'assistant-event notice-event'
  return 'assistant-event'
}

function eventLabel(event: AgentEvent): string {
  const code = String(event.data?.code ?? '')
  if (code === 'KNOWLEDGE_ANSWER') return 'Agent · general information'
  return 'Agent'
}

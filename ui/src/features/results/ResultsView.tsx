import { useEffect, useState } from 'react'
import { api, type Artifact } from '../../api/client'
import { useApp } from '../../app/store'
import { run } from '../../app/actions'
import type { Appearance } from '../../shell/appearances'
import { WeatherCharts } from './WeatherCharts'
const terminal = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])
export function ResultsView({ appearance }: { appearance: Appearance }) {
  const s = useApp()
  const [connection, setConnection] = useState('')
  useEffect(() => {
    let alive = true
    api
      .jobs()
      .then((r) => {
        if (alive) useApp.setState({ jobs: r.items, cursor: r.next_cursor || null })
      })
      .catch(() => {
        if (alive)
          setConnection('Cannot load job history. Start the backend or configure a session token.')
      })
    return () => {
      alive = false
    }
  }, [])
  useEffect(() => {
    if (!s.job || terminal.has(s.job.state)) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    const id = s.job.id
    async function poll() {
      try {
        const job = await api.job(id)
        if (!alive) return
        useApp.setState((state) => ({
          job: state.job?.id === id ? job : state.job,
          jobs: [job, ...state.jobs.filter((j) => j.id !== id)],
        }))
        setConnection('')
        attempts = 0
        if (!terminal.has(job.state)) timer = setTimeout(poll, 1500)
      } catch {
        if (alive) {
          setConnection('Connection interrupted. Retrying job status…')
          timer = setTimeout(poll, Math.min(1500 * 2 ** ++attempts, 15000))
        }
      }
    }
    timer = setTimeout(poll, 500)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [s.job?.id, s.job?.state])
  const bundle = s.job?.bundle
  const artifacts: Artifact[] = bundle
    ? [
        ...(bundle.weather || []),
        bundle.manifest,
        bundle.qc,
        bundle.request,
        bundle.plan,
        ...(bundle.additional || []),
      ]
    : []
  return (
    <section className="panel results-panel">
      <div className="section-heading">
        <div>
          <div className="eyebrow">JOBS & ARTIFACTS</div>
          <h1>Results with context</h1>
        </div>
        <button
          onClick={() =>
            api
              .jobs()
              .then((r) => {
                useApp.setState({ jobs: r.items, cursor: r.next_cursor || null })
                setConnection('')
              })
              .catch((e) => setConnection(String(e)))
          }
        >
          Refresh
        </button>
      </div>
      {connection && (
        <p className="warning" role="status">
          {connection}
        </p>
      )}
      {!s.jobs.length && (
        <div className="empty">
          <h2>No jobs yet</h2>
          <p>
            Review a weather request, then run its plan. Results, quality checks and source records
            will appear here.
          </p>
        </div>
      )}
      <div className="job-list">
        {s.jobs.map((j) => (
          <button
            className={s.job?.id === j.id ? 'selected' : ''}
            key={j.id}
            onClick={() => run({ type: 'selectJob', id: j.id })}
          >
            <span className={'badge ' + j.state}>{j.state.replaceAll('_', ' ')}</span>
            <span>{j.id.slice(0, 8)}</span>
            <small>
              {j.completed}/{j.total} outputs
            </small>
          </button>
        ))}
      </div>
      {s.cursor && (
        <button
          onClick={() =>
            api
              .jobs(s.cursor!)
              .then((r) =>
                useApp.setState({ jobs: [...s.jobs, ...r.items], cursor: r.next_cursor || null }),
              )
              .catch((e) => setConnection(String(e)))
          }
        >
          Load older jobs
        </button>
      )}
      {s.job && (
        <>
          <div className="section-heading">
            <h2>Job {s.job.id.slice(0, 8)}</h2>
            {!terminal.has(s.job.state) && (
              <button
                disabled={s.busy || s.job.cancellation_requested}
                onClick={() => run({ type: 'cancelJob', id: s.job!.id })}
              >
                {s.job.cancellation_requested ? 'Cancellation requested' : 'Cancel job'}
              </button>
            )}
          </div>
          <p className="muted">
            {s.job.completed} completed · {s.job.failed} failed · {s.job.total} planned. Provider
            calls may finish before cancellation takes effect.
          </p>
          {s.job.errors?.map((e, i) => (
            <p role="alert" className="error" key={i}>
              {e.code}: {e.message}
            </p>
          ))}
          <div className="artifact-list">
            {artifacts.map((a) => (
              <div key={a.id}>
                <button
                  disabled={s.busy}
                  onClick={() => run({ type: 'selectArtifact', artifact: a })}
                >
                  {a.role} <small>{a.path.split('/').pop()}</small>
                </button>
                <button
                  aria-label={'Download ' + a.role}
                  onClick={() =>
                    api.download(a).catch((e) => useApp.setState({ error: String(e) }))
                  }
                >
                  ↓ Download
                </button>
                {a.role === 'weather' && (
                  <button
                    onClick={() => {
                      s.editFuture({ baseline: a.id })
                      s.setMode('future')
                    }}
                  >
                    Use as baseline
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      {s.preview && (
        <section>
          <h2>Weather preview</h2>
          <p>
            {s.preview.total_rows.toLocaleString()} rows · {s.preview.calendar} · standard offset{' '}
            {s.preview.location.standard_offset_minutes} min
          </p>
          <p className="warning">
            Not certified simulation-ready. Review QC and source limitations.
          </p>
          <WeatherCharts preview={s.preview} appearance={appearance} />
          <div className="actions">
            <button
              disabled={s.preview.start === 0 || s.busy}
              onClick={() =>
                api
                  .preview(s.artifact!.id, Math.max(0, s.preview!.start - 168))
                  .then((preview) => useApp.setState({ preview }))
                  .catch((e) => setConnection(String(e)))
              }
            >
              Previous week
            </button>
            <span>
              Rows {s.preview.start + 1}–{s.preview.start + s.preview.rows.length}, UTC interval
              ends
            </span>
            <button
              disabled={s.preview.start + 168 >= s.preview.total_rows || s.busy}
              onClick={() =>
                api
                  .preview(s.artifact!.id, s.preview!.start + 168)
                  .then((preview) => useApp.setState({ preview }))
                  .catch((e) => setConnection(String(e)))
              }
            >
              Next week
            </button>
          </div>
          <h2>Monthly summary</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Mean °C</th>
                  <th>GHI Wh/m²</th>
                  <th>Valid solar / expected</th>
                </tr>
              </thead>
              <tbody>
                {s.preview.monthly.map((m) => (
                  <tr key={m.year + '-' + m.month}>
                    <td>
                      {m.year}-{String(m.month).padStart(2, '0')}
                    </td>
                    <td>{m.values.dry_bulb?.mean?.toFixed(1) ?? 'Missing'}</td>
                    <td>{m.values.ghi?.sum?.toFixed(0) ?? 'Missing'}</td>
                    <td>
                      {m.values.ghi?.valid ?? 0} / {m.expected}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Raw preview and source-year labels</summary>
            <pre>{JSON.stringify(s.preview, null, 2)}</pre>
          </details>
        </section>
      )}
      {s.detail != null && (
        <section>
          <h2>Artifact details</h2>
          <pre>{JSON.stringify(s.detail, null, 2)}</pre>
        </section>
      )}
    </section>
  )
}

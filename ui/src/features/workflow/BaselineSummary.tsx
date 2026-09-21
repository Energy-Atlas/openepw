import { useEffect, useState } from 'react'
import { api, type Artifact, type Schemas } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { canNavigate, deriveWorkflow } from '../../app/workflow'
import { formatOffset } from '../../app/timezone'

type Summary = Schemas['WeatherVisualization']

function sourceYears(years: (number | null)[]) {
  const known = [...new Set(years.filter((year): year is number => year != null))].sort()
  if (!known.length) return 'unknown'
  return known.length <= 3 ? known.join(', ') : `${known[0]}–${known.at(-1)}`
}

/** Dataset that produced a downloaded EPW, from the plan output whose name the path ends with. */
export function baselineDataset(state: ReturnType<typeof useApp.getState>, artifact: Artifact) {
  if (artifact.role === 'baseline') return 'Imported EPW'
  const output = (state.weatherPlan?.outputs ?? []).find((item) =>
    artifact.path.endsWith(item.name),
  )
  const selection = output?.dataset_selection
  return selection ? `${selection.provider} · ${selection.dataset}` : 'Downloaded EPW'
}

export function BaselineSummary({ baseline }: { baseline: Artifact }) {
  const state = useApp()
  const [summary, setSummary] = useState<{ id: string; value: Summary } | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setFailed(false)
    api
      .visualization(baseline.id, ['dry_bulb'], controller.signal)
      .then((value) => setSummary({ id: baseline.id, value }))
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true)
      })
    return () => controller.abort()
  }, [baseline.id])

  const current = summary?.id === baseline.id ? summary.value : null
  const downloadOpen = canNavigate(deriveWorkflow(state), 'download')
  const location = current?.location
  return (
    <div className="baseline-summary-card">
      <button
        type="button"
        className="baseline-artifact"
        onClick={() => run({ type: 'selectArtifact', artifact: baseline })}
      >
        <strong>{baseline.path.split('/').pop()}</strong>
        <small>
          {baselineDataset(state, baseline)} · {baseline.id.slice(0, 12)}
        </small>
      </button>
      {current ? (
        <dl className="baseline-facts">
          <div>
            <dt>Location</dt>
            <dd>
              {location?.name ? `${location.name} · ` : ''}
              {location?.lat.toFixed(3)}, {location?.lon.toFixed(3)}
            </dd>
          </div>
          <div>
            <dt>Period</dt>
            <dd>
              {current.timestamps[0]?.slice(0, 10)} – {current.timestamps.at(-1)?.slice(0, 10)}
            </dd>
          </div>
          <div>
            <dt>Time zone</dt>
            <dd>{formatOffset(location?.standard_offset_minutes ?? 0)} standard time</dd>
          </div>
          <div>
            <dt>Calendar</dt>
            <dd>
              {current.calendar} · {current.total_rows.toLocaleString()} rows
            </dd>
          </div>
          <div>
            <dt>Source years</dt>
            <dd>{sourceYears(current.source_years)}</dd>
          </div>
          <div>
            <dt>QC</dt>
            <dd>
              {current.simulation_ready
                ? 'Annual QC passed'
                : 'Annual QC passed; review before simulation'}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="empty-inline" role="status">
          {failed ? 'Baseline details are unavailable.' : 'Loading baseline details…'}
        </p>
      )}
      {current?.synthetic_chronology && (
        <p className="warning">Synthetic chronology: source years differ from timestamps.</p>
      )}
      {downloadOpen && baseline.role !== 'baseline' && (
        <button
          type="button"
          className="link-button"
          onClick={() => run({ type: 'navigate', stage: 'download' })}
        >
          Back to Download
        </button>
      )}
    </div>
  )
}

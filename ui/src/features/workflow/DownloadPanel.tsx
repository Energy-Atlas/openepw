import { useEffect, useMemo } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import type { DatasetSelection } from '../../app/workflow'
import { PlanReview } from '../request/PlanReview'
import { JobProgress } from './JobProgress'

type Candidate = NonNullable<ReturnType<typeof useApp.getState>['discovery']>['candidates'][number]
type CoverageLayer = ReturnType<typeof useApp.getState>['coverageLayers'][number]

function yearRange(years: number[]) {
  if (!years.length) return null
  const sorted = [...new Set(years)].sort((a, b) => a - b)
  return sorted.length === 1 ? String(sorted[0]) : `${sorted[0]}–${sorted.at(-1)}`
}

/** Dataset facts from discovery, plus documented coverage metadata for the same dataset. */
export function datasetFacts(candidates: Candidate[], coverage: CoverageLayer[]) {
  const source = candidates[0]?.source
  const layers = coverage.filter(
    (layer) => layer.provider === source?.provider && layer.dataset === source?.dataset,
  )
  const intervals = [...new Set(candidates.map((candidate) => candidate.interval_minutes))]
  const resolution =
    source?.resolution_km ?? layers.find((layer) => layer.resolution_km != null)?.resolution_km
  return {
    years: yearRange(candidates.flatMap((candidate) => candidate.available_years ?? [])),
    interval:
      intervals.length === 1 && intervals[0] != null
        ? intervals[0] === 60
          ? 'Hourly'
          : `${intervals[0]} min`
        : null,
    resolution: resolution != null ? `~${resolution} km` : null,
    access: source?.access_path ?? null,
    provisional: candidates.some((candidate) => candidate.source.provisional),
    limitations: [
      ...new Set([
        ...candidates.flatMap((candidate) => candidate.warnings ?? []),
        ...layers.flatMap((layer) => layer.limitations ?? []),
      ]),
    ],
    attribution: [
      ...new Set(
        [source?.citation, source?.license, ...layers.map((layer) => layer.attribution)].filter(
          (value): value is string => Boolean(value),
        ),
      ),
    ],
  }
}

function key(selection: DatasetSelection) {
  return `${selection.provider}\u0000${selection.dataset}\u0000${selection.product_id ?? ''}`
}

export function DownloadPanel() {
  const state = useApp()
  const groups = useMemo(() => {
    const grouped = new Map<
      string,
      { selection: DatasetSelection; candidates: NonNullable<typeof state.discovery>['candidates'] }
    >()
    for (const candidate of state.discovery?.candidates ?? []) {
      const selection = {
        provider: candidate.source.provider,
        dataset: candidate.source.dataset,
        product_id: candidate.product_id,
      }
      const id = key(selection)
      const group = grouped.get(id) ?? { selection, candidates: [] }
      group.candidates.push(candidate)
      grouped.set(id, group)
    }
    return [...grouped.values()]
  }, [state.discovery])
  const selected = new Set(state.selectedDatasets.map(key))
  const planCurrent =
    state.weatherPlanRequestVersion === state.requestVersion &&
    state.weatherPlanSelectionVersion === state.selectionVersion

  useEffect(() => {
    if (
      state.discoveryVersion !== state.requestVersion ||
      state.selectedDatasets.length === 0 ||
      planCurrent ||
      state.busy
    )
      return
    const timer = window.setTimeout(() => run({ type: 'planWeather' }), 300)
    return () => window.clearTimeout(timer)
  }, [
    planCurrent,
    state.discoveryVersion,
    state.requestVersion,
    state.selectedDatasets,
    state.selectionVersion,
    state.busy,
  ])

  const artifacts = [
    ...state.importedArtifacts,
    ...state.downloadJobs.flatMap((job) => job.bundle?.weather ?? []),
  ]

  const [latestJob, ...earlierJobs] = state.downloadJobs

  return (
    <div className="stage-body">
      {latestJob && <JobProgress job={latestJob} kind="weather" />}
      <section className="control-section upstream-summary">
        <h2>Explore query</h2>
        <p>
          {Array.isArray(state.draft.locations)
            ? `${state.draft.locations.length} points`
            : 'One geometry'}{' '}
          · {state.draft.product}
          {state.draft.years?.length ? ` · ${state.draft.years.join(', ')}` : ''}
        </p>
        {state.discoveryVersion !== state.requestVersion && (
          <p className="warning">The Explore query changed. Refresh availability before running.</p>
        )}
      </section>

      <section className="control-section">
        <h2>Datasets</h2>
        {!groups.length && (
          <p className="empty-inline">
            No current discovery. Return to Explore and find availability.
          </p>
        )}
        <div className="dataset-list">
          {groups.map(({ selection, candidates }) => {
            const id = key(selection)
            const reasons = [
              ...new Set(candidates.flatMap((candidate) => candidate.selection_reasons)),
            ]
            const credentials = [
              ...new Set(candidates.flatMap((candidate) => candidate.requires_credentials)),
            ]
            const missing = [
              ...new Set(candidates.flatMap((candidate) => candidate.missing_fields)),
            ]
            const available = candidates.length
            return (
              <article className="dataset-row" key={id}>
                <label className="check-row">
                  <input
                    type="checkbox"
                    aria-label={`${selection.provider} / ${selection.dataset}`}
                    checked={selected.has(id)}
                    onChange={(event) =>
                      run({
                        type: 'selectDatasets',
                        selections: event.target.checked
                          ? [...state.selectedDatasets, selection]
                          : state.selectedDatasets.filter((item) => key(item) !== id),
                      })
                    }
                  />
                  <span>
                    <strong>
                      {selection.provider} / {selection.dataset}
                    </strong>
                    <small>
                      Available at {available} sampled {available === 1 ? 'point' : 'points'}
                    </small>
                  </span>
                </label>
                {reasons.map((reason) => (
                  <p className="selection-reason" key={reason}>
                    Recommended: {reason}
                  </p>
                ))}
                <DatasetFacts candidates={candidates} coverage={state.coverageLayers} />
                {credentials.length > 0 && (
                  <p className="dataset-credentials">
                    Requires server credentials: {credentials.join(', ')}
                  </p>
                )}
                {missing.length > 0 && <p className="warning">Missing: {missing.join(', ')}</p>}
              </article>
            )
          })}
        </div>
        {state.discovery?.issues?.map((issue, index) => (
          <p className="warning" key={`${issue.code}-${index}`}>
            {issue.message}
          </p>
        ))}
      </section>

      <PlanReview plan={state.weatherPlan} current={planCurrent} />

      <section className="control-section">
        <h2>Jobs and EPWs</h2>
        <label>
          Import an existing EPW
          <input
            type="file"
            accept=".epw"
            disabled={state.busy}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) run({ type: 'uploadBaseline', file })
            }}
          />
          <small>Parsing makes the file eligible; it does not certify simulation readiness.</small>
        </label>
        {earlierJobs.map((job) => (
          <article className="job-summary" key={job.id}>
            <span className={`badge ${job.state}`}>{job.state.replaceAll('_', ' ')}</span>
            <strong>{job.id.slice(0, 8)}</strong>
            <span>
              {job.completed} complete, {job.failed} failed
            </span>
          </article>
        ))}
        <div className="stage-artifacts">
          {artifacts.map((artifact) => (
            <button
              type="button"
              key={artifact.id}
              onClick={() => run({ type: 'selectArtifact', artifact })}
            >
              <span>{artifact.path.split('/').pop()}</span>
              <small>{artifact.role === 'baseline' ? 'Imported EPW' : 'Generated EPW'}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}

function DatasetFacts({
  candidates,
  coverage,
}: {
  candidates: Candidate[]
  coverage: CoverageLayer[]
}) {
  const facts = datasetFacts(candidates, coverage)
  const summary = [
    facts.years && ['Years', facts.years],
    facts.interval && ['Interval', facts.interval],
    facts.resolution && ['Resolution', facts.resolution],
    facts.access && ['Access', facts.access],
  ].filter((item): item is [string, string] => Boolean(item))
  return (
    <>
      {summary.length > 0 && (
        <dl className="dataset-facts">
          {summary.map(([term, value]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{value}</dd>
            </div>
          ))}
          {facts.provisional && (
            <div>
              <dt>Status</dt>
              <dd>Provisional</dd>
            </div>
          )}
        </dl>
      )}
      {(facts.limitations.length > 0 || facts.attribution.length > 0) && (
        <details className="dataset-notes">
          <summary>Limitations and attribution</summary>
          {facts.limitations.map((limitation) => (
            <p key={limitation}>{limitation}</p>
          ))}
          {facts.attribution.map((attribution) => (
            <p key={attribution} className="dataset-attribution">
              {attribution}
            </p>
          ))}
        </details>
      )}
    </>
  )
}

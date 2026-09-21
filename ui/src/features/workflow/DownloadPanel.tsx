import { useEffect, useMemo } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import type { DatasetSelection } from '../../app/workflow'
import { PlanReview } from '../request/PlanReview'

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

  return (
    <div className="stage-body">
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
                {credentials.length > 0 && <small>Requires {credentials.join(', ')}</small>}
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
        {state.downloadJobs.map((job) => (
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

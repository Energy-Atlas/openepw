import { useEffect } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { FutureForm } from '../request/FutureForm'
import { PlanReview } from '../request/PlanReview'

export function ProjectPanel() {
  const state = useApp()
  const baseline = state.activeWeatherArtifact
  const planCurrent =
    state.futurePlanVersion === state.futureVersion && state.futurePlanBaselineId === baseline?.id

  useEffect(() => {
    if (!baseline || state.future.baseline === baseline.id) return
    run({ type: 'editFuture', patch: { baseline: baseline.id } })
  }, [baseline, state.future.baseline])

  useEffect(() => {
    if (!baseline || !state.future.baseline || planCurrent || state.busy) return
    const timer = window.setTimeout(() => run({ type: 'planFuture' }), 300)
    return () => window.clearTimeout(timer)
  }, [baseline, planCurrent, state.future.baseline, state.futureVersion, state.busy])

  return (
    <div className="stage-body">
      <section className="control-section baseline-summary">
        <h2>Active baseline</h2>
        {baseline ? (
          <button
            type="button"
            className="baseline-artifact"
            onClick={() => run({ type: 'selectArtifact', artifact: baseline })}
          >
            <strong>{baseline.path.split('/').pop()}</strong>
            <small>{baseline.id.slice(0, 12)} · parsed and annual-QC validated EPW</small>
          </button>
        ) : (
          <p className="notice">Select a generated EPW in Download or import a baseline.</p>
        )}
      </section>
      <FutureForm />
      <p className="notice projection-note">
        A scenario projection explores plausible future conditions. It is not a forecast.
      </p>
      <PlanReview plan={state.futurePlan} current={planCurrent} />
    </div>
  )
}

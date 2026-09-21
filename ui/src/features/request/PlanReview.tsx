import type { Plan } from '../../api/client'

export function PlanReview({ plan, current }: { plan: Plan | null; current: boolean }) {
  return (
    <section className="control-section plan-review" aria-label="Reviewed plan">
      <h2>Reviewed plan</h2>
      {!plan ? (
        <p className="empty-inline">
          The plan will update after the required selections are ready.
        </p>
      ) : (
        <>
          <div className="plan-metrics">
            <span>
              <strong>{plan.outputs?.length || 0}</strong> EPW mappings
            </span>
            <span>
              <strong>{plan.tasks?.length || 0}</strong> source tasks
            </span>
          </div>
          {!current && <p className="warning">This plan is stale and cannot run.</p>}
          {plan.estimated_bytes != null && (
            <p>{(plan.estimated_bytes / 1e9).toFixed(2)} GB conservative decoded estimate</p>
          )}
          {plan.warnings?.map((warning, index) => (
            <p className="warning" key={`warning-${index}`}>
              {warning}
            </p>
          ))}
          {plan.issues?.map((issue, index) => (
            <p
              className={issue.severity === 'error' ? 'error' : 'warning'}
              key={`${issue.code}-${index}`}
            >
              {issue.message}
            </p>
          ))}
        </>
      )}
    </section>
  )
}

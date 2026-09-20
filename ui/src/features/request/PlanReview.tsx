import { useApp } from '../../app/store'
import { run } from '../../app/actions'
export function PlanReview() {
  const s = useApp()
  return (
    <>
      {s.error && (
        <p role="alert" className="error">
          {s.error}
        </p>
      )}
      {s.busy && (
        <p role="status">
          Working with the backend…{' '}
          <button onClick={() => run({ type: 'cancelActive' })}>Stop client request</button>
        </p>
      )}
      {s.plan && (
        <section className="plan-review">
          <div className="eyebrow">PLAN READY</div>
          <h2>
            {s.plan.tasks?.length || 0} source tasks · {s.plan.outputs?.length || 0} mappings
          </h2>
          {s.plan.estimated_bytes != null && (
            <p>
              Conservative source estimate: {(s.plan.estimated_bytes / 1e9).toFixed(2)} GB decoded
            </p>
          )}
          {s.plan.warnings?.map((w, i) => (
            <p className="warning" key={i}>
              {w}
            </p>
          ))}
          <details>
            <summary>Request and plan details</summary>
            <pre>{JSON.stringify(s.plan, null, 2)}</pre>
          </details>
          <button
            className="primary"
            disabled={s.busy || s.submitted}
            onClick={() => run({ type: 'submitPlan' })}
          >
            {s.submitted ? 'Job submitted' : 'Run reviewed plan'}
          </button>
          {s.submitted && (
            <button
              onClick={() => useApp.setState({ submitted: false, submitKey: crypto.randomUUID() })}
            >
              Prepare intentional rerun
            </button>
          )}
        </section>
      )}
    </>
  )
}

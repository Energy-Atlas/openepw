import { useApp } from '../../app/store'
import { run } from '../../app/actions'
import { recipes, runRecipe } from './runner'
export function AgentPanel() {
  const s = useApp()
  return (
    <section className="panel agent-panel">
      <div className="section-heading">
        <h1>Agent</h1>
        <span className="badge">Scripted · no LLM</span>
      </div>
      <p className="muted">
        Real tools, explicit steps. Set parameters in Request, then choose a workflow.
      </p>
      <div className="recipe-list">
        {recipes.map((r) => (
          <button
            key={r.id}
            disabled={
              s.busy ||
              (r.id === 'run' && (!s.plan || s.submitted)) ||
              (r.id === 'inspect' && !s.artifact)
            }
            title={r.description}
            onClick={() =>
              void runRecipe(r.id).catch((e) => {
                s.log(String(e), 'error')
                useApp.setState({ error: String(e) })
              })
            }
          >
            {r.label}
            <small>{r.description}</small>
          </button>
        ))}
      </div>
      <h2>Action log</h2>
      <div className="transcript" role="log" aria-live="polite">
        {!s.logs.length && (
          <p className="muted">
            Tool calls and observed results will appear here. No simulated progress.
          </p>
        )}
        {s.logs.map((l) => (
          <article className={l.kind} key={l.id}>
            <small>
              {l.kind === 'tool' ? 'TOOL CALL' : l.kind === 'error' ? 'FAILED' : 'OBSERVED'}
            </small>
            <p>{l.text}</p>
          </article>
        ))}
      </div>
      {s.busy && (
        <button onClick={() => run({ type: 'cancelActive' })}>Stop client operation</button>
      )}
      {s.job &&
        !['completed', 'failed', 'partially_completed', 'cancelled'].includes(s.job.state) && (
          <button onClick={() => run({ type: 'cancelJob', id: s.job!.id })}>
            Cancel server job {s.job.id.slice(0, 8)}
          </button>
        )}
    </section>
  )
}

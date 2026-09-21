import { Send, ShieldAlert, Terminal, Wrench } from 'lucide-react'
import { useState } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { recipes, runRecipe } from './runner'

type Pending = {
  requiresConfirmation: true
  title: string
  description: string
}

export function AgentPanel() {
  const state = useApp()
  const [pending, setPending] = useState<Pending | null>(null)
  const [message, setMessage] = useState('')

  async function invoke(id: string, confirmed = false) {
    try {
      const result = await runRecipe(id, undefined, confirmed)
      if (result && typeof result === 'object' && 'requiresConfirmation' in result)
        setPending(result as Pending)
      else setPending(null)
    } catch (error) {
      state.log(String(error), 'error')
      useApp.setState({ error: String(error) })
    }
  }

  function submit() {
    const normalized = message.trim().toLowerCase()
    setMessage('')
    const recipe = normalized.includes('inspect')
      ? 'inspect'
      : normalized.includes('plan')
        ? 'plan'
        : normalized.includes('run') ||
            normalized.includes('download') ||
            normalized.includes('generate')
          ? 'run'
          : normalized.includes('source') || normalized.includes('availability')
            ? 'sources'
            : null
    if (recipe) void invoke(recipe)
    else
      state.log(
        'Scripted Agent accepts the suggested actions only. Edit controls directly for other changes.',
      )
  }

  return (
    <section className="panel agent-panel">
      <header className="agent-header">
        <div>
          <h1>Agent</h1>
          <p>Observed actions and results</p>
        </div>
        <span className="badge">Scripted</span>
      </header>

      <div className="agent-transcript" role="log" aria-label="Agent transcript" aria-live="polite">
        {!state.logs.length && (
          <article className="agent-intro">
            <Terminal size={15} aria-hidden="true" />
            <p>
              I can run the same registered actions as the controls. I do not interpret general
              free-form requests yet.
            </p>
          </article>
        )}
        {state.logs.map((entry) => (
          <article className={`agent-entry ${entry.kind}`} key={entry.id}>
            <div>
              {entry.kind === 'tool' ? <Wrench size={13} aria-hidden="true" /> : null}
              <small>
                {entry.kind === 'tool'
                  ? 'Tool call'
                  : entry.kind === 'error'
                    ? 'Failed'
                    : 'Observed'}
              </small>
            </div>
            <p>{entry.text}</p>
          </article>
        ))}
        {pending && (
          <article className="agent-confirmation" aria-label={pending.title}>
            <div>
              <ShieldAlert size={15} aria-hidden="true" />
              <strong>Confirmation required</strong>
            </div>
            <p>{pending.title}</p>
            <small>{pending.description}</small>
            <div className="actions">
              <button type="button" className="primary" onClick={() => void invoke('run', true)}>
                Confirm
              </button>
              <button type="button" onClick={() => setPending(null)}>
                Keep reviewing
              </button>
            </div>
          </article>
        )}
      </div>

      <div className="agent-controls">
        <p>Suggested actions</p>
        <div className="agent-suggestions">
          {recipes.map((recipe) => (
            <button
              type="button"
              key={recipe.id}
              disabled={
                state.busy ||
                (recipe.id === 'inspect' && !state.artifact) ||
                (recipe.id === 'future' && !state.activeWeatherArtifact)
              }
              title={recipe.description}
              onClick={() => void invoke(recipe.id)}
            >
              {recipe.label}
            </button>
          ))}
        </div>
        {state.busy && (
          <p className="client-cancel">
            <button type="button" onClick={() => run({ type: 'cancelActive' })}>
              Stop waiting on this client
            </button>
            <small>An accepted server job continues until explicitly cancelled.</small>
          </p>
        )}
        {state.job &&
          !['completed', 'failed', 'partially_completed', 'cancelled'].includes(
            state.job.state,
          ) && (
            <button type="button" onClick={() => run({ type: 'cancelJob', id: state.job!.id })}>
              Cancel server job {state.job.id.slice(0, 8)}
            </button>
          )}
        <form
          className="agent-composer"
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <label htmlFor="agent-message">Scripted command</label>
          <div>
            <textarea
              id="agent-message"
              rows={2}
              value={message}
              placeholder="Try “refresh the plan”"
              onChange={(event) => setMessage(event.target.value)}
            />
            <button type="submit" aria-label="Send scripted command" disabled={!message.trim()}>
              <Send size={15} aria-hidden="true" />
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}

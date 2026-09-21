import { ChevronDown, Play } from 'lucide-react'
import { useState } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { deriveWorkflow } from '../../app/workflow'

export function RunSplitButton() {
  const state = useApp()
  const workflow = deriveWorkflow(state)
  const [open, setOpen] = useState(false)
  const blocked = !workflow.run.enabled

  function primary() {
    if (blocked) return
    run({ type: 'runCurrentStage', confirmed: state.stage !== 'explore' })
  }

  return (
    <div className={`run-control ${blocked ? 'run-control-idle' : ''}`}>
      <div className="run-split">
        <button
          type="button"
          className="run-primary"
          aria-label={workflow.run.label}
          aria-disabled={blocked || undefined}
          title={workflow.run.reason ?? workflow.run.label}
          onClick={primary}
        >
          <Play size={14} aria-hidden="true" />
          Run
        </button>
        <button
          type="button"
          className="run-menu-trigger"
          aria-label="More run options"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      </div>
      {workflow.run.reason && <span className="run-reason">{workflow.run.reason}</span>}
      {open && (
        <div className="run-menu" role="menu">
          {state.stage === 'explore' && (
            <>
              <button role="menuitem" onClick={() => run({ type: 'previewSpatial' })}>
                Refresh sample preview
              </button>
              <button role="menuitem" onClick={() => run({ type: 'discover' })}>
                Refresh availability
              </button>
            </>
          )}
          {state.stage === 'download' && (
            <>
              <button role="menuitem" onClick={() => run({ type: 'planWeather' })}>
                Refresh reviewed plan
              </button>
              <button role="menuitem" onClick={() => run({ type: 'rerunPlan' })}>
                Retry or rerun plan
              </button>
            </>
          )}
          {state.stage === 'project' && (
            <>
              <button role="menuitem" onClick={() => run({ type: 'planFuture' })}>
                Refresh projection plan
              </button>
              <button role="menuitem" onClick={() => run({ type: 'rerunPlan' })}>
                Generate another run
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

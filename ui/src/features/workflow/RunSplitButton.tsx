import { ChevronDown, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { deriveWorkflow } from '../../app/workflow'
import { ModalDialog } from '../../shell/ModalDialog'

export function RunSplitButton() {
  const state = useApp()
  const workflow = deriveWorkflow(state)
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState<'run' | 'rerun' | null>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const runPrimary = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const confirmButton = useRef<HTMLButtonElement>(null)
  const confirmationOpener = useRef<HTMLElement | null>(null)
  const blocked = !workflow.run.enabled
  const confirmationPlan = state.stage === 'project' ? state.futurePlan : state.weatherPlan

  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
  }, [open])

  useEffect(() => {
    if (confirming) confirmButton.current?.focus()
  }, [confirming])

  function primary() {
    if (blocked) return
    if (state.stage !== 'explore') {
      confirmationOpener.current = runPrimary.current
      setConfirming('run')
      return
    }
    run({ type: 'runCurrentStage' })
  }

  function askToRerun() {
    confirmationOpener.current = menuTrigger.current
    setOpen(false)
    setConfirming('rerun')
  }

  return (
    <div className={`run-control ${blocked ? 'run-control-idle' : ''}`}>
      <div className="run-split">
        <button
          type="button"
          className="run-primary"
          ref={runPrimary}
          aria-label={workflow.run.label}
          aria-disabled={blocked || undefined}
          aria-describedby={workflow.run.reason ? 'run-reason' : undefined}
          title={workflow.run.reason ?? workflow.run.label}
          onClick={primary}
        >
          <Play size={14} aria-hidden="true" />
          Run
        </button>
        <button
          type="button"
          className="run-menu-trigger"
          ref={menuTrigger}
          aria-label="More run options"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      </div>
      {workflow.run.reason && (
        <span className="run-reason" id="run-reason">
          {workflow.run.reason}
        </span>
      )}
      {open && (
        <div
          className="run-menu"
          role="menu"
          ref={menu}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false)
              menuTrigger.current?.focus()
            }
          }}
        >
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
              <button role="menuitem" onClick={askToRerun}>
                Retry or rerun plan
              </button>
            </>
          )}
          {state.stage === 'project' && (
            <>
              <button role="menuitem" onClick={() => run({ type: 'planFuture' })}>
                Refresh projection plan
              </button>
              <button role="menuitem" onClick={askToRerun}>
                Generate another run
              </button>
            </>
          )}
        </div>
      )}
      {confirming && (
        <ModalDialog
          className="run-confirmation"
          role="alertdialog"
          ariaLabel={`Confirm ${workflow.run.label}`}
          onClose={() => setConfirming(null)}
          restoreFocus={confirmationOpener}
        >
          <strong>
            {confirming === 'rerun' ? 'Run the reviewed plan again?' : `${workflow.run.label}?`}
          </strong>
          <p>This starts a server job using the current reviewed plan.</p>
          {confirmationPlan && (
            <dl className="confirmation-facts">
              <div>
                <dt>{confirmationPlan.kind === 'future' ? 'Projection outputs' : 'EPW outputs'}</dt>
                <dd>{new Set(confirmationPlan.outputs?.map((output) => output.name)).size}</dd>
              </div>
              <div>
                <dt>Source tasks</dt>
                <dd>{confirmationPlan.tasks?.length ?? 0}</dd>
              </div>
            </dl>
          )}
          <p>Progress appears in the stage panel and status bar; History keeps every job.</p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              ref={confirmButton}
              data-autofocus
              onClick={() => {
                const action = confirming === 'rerun' ? 'rerunPlan' : 'runCurrentStage'
                setConfirming(null)
                run({ type: action, confirmed: true })
              }}
            >
              Confirm job
            </button>
            <button type="button" onClick={() => setConfirming(null)}>
              Keep reviewing
            </button>
          </div>
        </ModalDialog>
      )}
    </div>
  )
}

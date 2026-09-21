import { Bot, CloudSun, ExternalLink, History, PanelLeft, Settings2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { setToken } from '../api/client'
import { confirmPendingAction, dismissPendingAction, run } from './actions'
import { useApp } from './store'
import { canNavigate, deriveWorkflow, type Stage } from './workflow'
import { AgentPanel } from '../features/agent/AgentPanel'
import { MapView } from '../features/map/MapView'
import { HistoryDrawer, useJobMonitor, useJobReconcile } from '../features/results/HistoryDrawer'
import { WeatherInspector } from '../features/results/WeatherInspector'
import { RunSplitButton } from '../features/workflow/RunSplitButton'
import { StagePanel } from '../features/workflow/StagePanel'
import { isActiveJob, JobProgress } from '../features/workflow/JobProgress'
import { APPEARANCE_LIST, type AppearancePreference } from '../shell/appearances'
import { isNarrow, resizeFromPointer } from '../shell/layout'
import { nextDrawer, type Drawer } from '../shell/panels'
import { useTheme } from '../shell/theme'
import { useAnnouncements } from '../shell/announcements'
import { ModalDialog } from '../shell/ModalDialog'

const stages: Stage[] = ['explore', 'download', 'project']

export function App() {
  const state = useApp()
  const workflow = deriveWorkflow(state)
  const { preference, setPreference, appearance } = useTheme()
  const [narrow, setNarrow] = useState(isNarrow)
  const [drawer, setDrawer] = useState<Drawer>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const controlsTrigger = useRef<HTMLButtonElement>(null)
  const agentTrigger = useRef<HTMLButtonElement>(null)
  const controlsPanel = useRef<HTMLElement>(null)
  const agentPanel = useRef<HTMLElement>(null)
  const historyTrigger = useRef<HTMLButtonElement>(null)
  useJobReconcile()
  useJobMonitor()
  const announcement = useAnnouncements(state.stage, state.job)

  useEffect(() => {
    const resize = () => setNarrow(isNarrow())
    addEventListener('resize', resize)
    return () => removeEventListener('resize', resize)
  }, [])

  useEffect(() => {
    if (!narrow || !drawer) return
    const panel = drawer === 'controls' ? controlsPanel.current : agentPanel.current
    panel?.querySelector<HTMLElement>('button, input, select, textarea, [tabindex]')?.focus()
  }, [drawer, narrow])

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      // A modal dialog handles its own Escape; do not also close the drawer beneath it.
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (historyOpen) {
        setHistoryOpen(false)
        historyTrigger.current?.focus()
        return
      }
      if (settingsOpen) {
        setSettingsOpen(false)
        return
      }
      if (drawer) closeDrawer(drawer)
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  })

  function closeDrawer(closing: Exclude<Drawer, null>) {
    setDrawer(null)
    ;(closing === 'controls' ? controlsTrigger : agentTrigger).current?.focus()
  }

  function toggle(requested: Exclude<Drawer, null>) {
    const next = nextDrawer(drawer, requested)
    if (next === null && drawer) closeDrawer(drawer)
    else setDrawer(next)
  }

  function startResize(
    panel: 'controls' | 'agent',
    side: 'left' | 'right',
    event: React.PointerEvent,
  ) {
    const origin = event.clientX
    const initial = state.panelSizes[panel]
    const move = (pointer: PointerEvent) => {
      run({
        type: 'setPanelSize',
        panel,
        size: resizeFromPointer(side, origin, initial, pointer.clientX),
      })
    }
    const stop = () => {
      removeEventListener('pointermove', move)
      removeEventListener('pointerup', stop)
    }
    addEventListener('pointermove', move)
    addEventListener('pointerup', stop)
  }

  function resizeWithKeyboard(
    panel: 'controls' | 'agent',
    side: 'left' | 'right',
    event: React.KeyboardEvent,
  ) {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
    event.preventDefault()
    const outward = side === 'left' ? event.key === 'ArrowRight' : event.key === 'ArrowLeft'
    run({ type: 'setPanelSize', panel, size: state.panelSizes[panel] + (outward ? 10 : -10) })
  }

  return (
    <div className="app cockpit-app">
      <header className="app-header cockpit-header">
        <div className="brand">
          <CloudSun size={21} aria-hidden="true" />
          <strong>openepw</strong>
        </div>
        <nav className="stage-stepper" aria-label="Workflow stages">
          {narrow ? (
            <select
              className="stage-select"
              aria-label="Workflow stage"
              value={state.stage}
              onChange={(event) => run({ type: 'navigate', stage: event.target.value as Stage })}
            >
              {stages.map((stage, index) => (
                <option key={stage} value={stage} disabled={!canNavigate(workflow, stage)}>
                  {index + 1}. {stage[0].toUpperCase() + stage.slice(1)}
                  {workflow.stages[stage].complete ? ' ✓' : ''}
                </option>
              ))}
            </select>
          ) : (
            stages.map((stage, index) => {
              const available = canNavigate(workflow, stage)
              return (
                <button
                  type="button"
                  key={stage}
                  aria-label={stage[0].toUpperCase() + stage.slice(1)}
                  aria-current={state.stage === stage ? 'step' : undefined}
                  aria-disabled={!available || undefined}
                  onClick={() => available && run({ type: 'navigate', stage })}
                >
                  <span>{index + 1}</span>
                  <strong>{stage[0].toUpperCase() + stage.slice(1)}</strong>
                  {workflow.stages[stage].complete && <i aria-label="complete">✓</i>}
                </button>
              )
            })
          )}
        </nav>
        <div className="header-actions">
          <button
            type="button"
            ref={historyTrigger}
            aria-label="History"
            onClick={() => setHistoryOpen(true)}
          >
            <History size={15} aria-hidden="true" />
            <span>History</span>
          </button>
          <RunSplitButton />
          <div className="settings-anchor">
            <button
              type="button"
              aria-label="Settings"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen((value) => !value)}
            >
              <Settings2 size={16} aria-hidden="true" />
            </button>
            {settingsOpen && (
              <div className="settings-popover" role="dialog" aria-label="Workspace settings">
                <label>
                  Appearance
                  <select
                    value={preference}
                    onChange={(event) => setPreference(event.target.value as AppearancePreference)}
                  >
                    <option value="system">System</option>
                    {APPEARANCE_LIST.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Session token
                  <input
                    type="password"
                    autoComplete="off"
                    onChange={(event) => setToken(event.target.value)}
                  />
                </label>
                <a href="/docs" target="_blank" rel="noreferrer">
                  API documentation <ExternalLink size={12} aria-hidden="true" />
                </a>
                <a href="https://github.com/Energy-Atlas/openepw" target="_blank" rel="noreferrer">
                  Source code <ExternalLink size={12} aria-hidden="true" />
                </a>
              </div>
            )}
          </div>
        </div>
      </header>

      <main
        className={`cockpit ${narrow ? 'cockpit-narrow' : ''}`}
        style={
          {
            '--controls-width': `${state.panelSizes.controls}px`,
            '--agent-width': `${state.panelSizes.agent}px`,
          } as React.CSSProperties
        }
      >
        {narrow && (
          <div className="drawer-triggers" aria-label="Workspace panels">
            <button
              type="button"
              ref={controlsTrigger}
              aria-expanded={drawer === 'controls'}
              onClick={() => toggle('controls')}
            >
              <PanelLeft size={15} aria-hidden="true" /> Controls
            </button>
            <button
              type="button"
              ref={agentTrigger}
              aria-label="Agent panel"
              aria-expanded={drawer === 'agent'}
              onClick={() => toggle('agent')}
            >
              <Bot size={15} aria-hidden="true" /> Agent
            </button>
          </div>
        )}
        <div
          className="map-workspace"
          aria-label="Weather map workspace"
          // A narrow drawer is modal over the map: keep focus and pointer input out of it.
          inert={narrow && drawer !== null}
        >
          <MapView appearance={appearance} />
          {state.inspector.open && state.visualization && (
            <WeatherInspector appearance={appearance} />
          )}
          {!state.inspector.open && state.visualization && (
            <button
              type="button"
              className="inspector-reopen"
              onClick={() => run({ type: 'setInspector', open: true })}
            >
              Inspect {state.artifact?.path.split('/').pop() ?? 'weather'}
            </button>
          )}
        </div>
        <aside
          ref={controlsPanel}
          className="cockpit-panel cockpit-surface controls-panel"
          role="complementary"
          aria-label="Stage controls"
          data-open={!narrow || drawer === 'controls'}
          style={{ width: narrow ? undefined : state.panelSizes.controls }}
        >
          <StagePanel />
          {!narrow && (
            <div
              className="panel-resizer panel-resizer-right"
              role="separator"
              tabIndex={0}
              aria-label="Resize stage controls"
              aria-valuemin={280}
              aria-valuemax={520}
              aria-valuenow={state.panelSizes.controls}
              onPointerDown={(event) => startResize('controls', 'left', event)}
              onKeyDown={(event) => resizeWithKeyboard('controls', 'left', event)}
            />
          )}
        </aside>
        <aside
          ref={agentPanel}
          className="cockpit-panel cockpit-surface agent-sidecar"
          role="complementary"
          aria-label="Agent"
          data-open={!narrow || drawer === 'agent'}
          style={{ width: narrow ? undefined : state.panelSizes.agent }}
        >
          <AgentPanel />
          {!narrow && (
            <div
              className="panel-resizer panel-resizer-left"
              role="separator"
              tabIndex={0}
              aria-label="Resize Agent"
              aria-valuemin={280}
              aria-valuemax={520}
              aria-valuenow={state.panelSizes.agent}
              onPointerDown={(event) => startResize('agent', 'right', event)}
              onKeyDown={(event) => resizeWithKeyboard('agent', 'right', event)}
            />
          )}
        </aside>
      </main>

      <HistoryDrawer
        open={historyOpen}
        restoreFocus={historyTrigger}
        onClose={() => {
          setHistoryOpen(false)
          historyTrigger.current?.focus()
        }}
      />
      {state.pendingConfirmation && (
        <ModalDialog
          className="run-confirmation global-confirmation"
          role="alertdialog"
          labelledBy="invalidation-title"
          onClose={dismissPendingAction}
        >
          <strong id="invalidation-title">{state.pendingConfirmation.title}</strong>
          <p>{state.pendingConfirmation.description}</p>
          <div className="actions">
            <button type="button" className="primary" data-autofocus onClick={confirmPendingAction}>
              Apply change
            </button>
            <button type="button" onClick={dismissPendingAction}>
              Keep current work
            </button>
          </div>
        </ModalDialog>
      )}
      <p className="sr-only" role="status" aria-live="polite" data-testid="announcer">
        {announcement}
      </p>
      <footer className="status-bar">
        <span className="status-dot" /> Local workspace
        <span className="status-detail">Single user · scientific provenance retained</span>
        <span className="spacer" />
        {state.job && isActiveJob(state.job) ? (
          <JobProgress job={state.job} kind={state.job.kind} compact />
        ) : (
          <span>
            {state.busy
              ? 'Backend request in progress'
              : state.job
                ? `Job ${state.job.state.replaceAll('_', ' ')}`
                : workflow.run.reason || 'Ready'}
          </span>
        )}
      </footer>
    </div>
  )
}

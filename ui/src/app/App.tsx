import { Bot, CloudSun, ExternalLink, History, PanelLeft, Settings2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { setToken } from '../api/client'
import { run } from './actions'
import { useApp } from './store'
import { canNavigate, deriveWorkflow, type Stage } from './workflow'
import { AgentPanel } from '../features/agent/AgentPanel'
import { MapView } from '../features/map/MapView'
import { HistoryDrawer, useJobMonitor } from '../features/results/HistoryDrawer'
import { RunSplitButton } from '../features/workflow/RunSplitButton'
import { StagePanel } from '../features/workflow/StagePanel'
import { APPEARANCE_LIST, type AppearancePreference } from '../shell/appearances'
import { isNarrow, resizeFromPointer } from '../shell/layout'
import { clampPanelSize, nextDrawer, type Drawer } from '../shell/panels'
import { useTheme } from '../shell/theme'

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
  useJobMonitor()

  useEffect(() => {
    const resize = () => setNarrow(isNarrow())
    addEventListener('resize', resize)
    return () => removeEventListener('resize', resize)
  }, [])

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (historyOpen) {
        setHistoryOpen(false)
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
      const size = clampPanelSize(panel, resizeFromPointer(side, origin, initial, pointer.clientX))
      useApp.setState((current) => ({ panelSizes: { ...current.panelSizes, [panel]: size } }))
    }
    const stop = () => {
      removeEventListener('pointermove', move)
      removeEventListener('pointerup', stop)
    }
    addEventListener('pointermove', move)
    addEventListener('pointerup', stop)
  }

  return (
    <div className="app cockpit-app">
      <header className="app-header cockpit-header">
        <div className="brand">
          <CloudSun size={21} aria-hidden="true" />
          <strong>openepw</strong>
        </div>
        <nav className="stage-stepper" aria-label="Workflow stages">
          {stages.map((stage, index) => {
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
          })}
        </nav>
        <div className="header-actions">
          <button type="button" onClick={() => setHistoryOpen(true)}>
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

      <main className={`cockpit ${narrow ? 'cockpit-narrow' : ''}`}>
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
        <div className="map-workspace" aria-label="Weather map workspace">
          <MapView appearance={appearance} />
          {state.inspector.open && state.visualization && (
            <section className="inspector-slot" aria-label="Weather inspector">
              Weather inspector · {state.visualization.total_rows.toLocaleString()} rows
            </section>
          )}
        </div>
        <aside
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
              aria-label="Resize stage controls"
              onPointerDown={(event) => startResize('controls', 'left', event)}
            />
          )}
        </aside>
        <aside
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
              aria-label="Resize Agent"
              onPointerDown={(event) => startResize('agent', 'right', event)}
            />
          )}
        </aside>
      </main>

      <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
      <footer className="status-bar">
        <span className="status-dot" /> Local workspace
        <span className="status-detail">Single user · scientific provenance retained</span>
        <span className="spacer" />
        <span>
          {state.busy
            ? 'Backend request in progress'
            : state.job
              ? `Job ${state.job.state.replaceAll('_', ' ')}`
              : workflow.run.reason || 'Ready'}
        </span>
      </footer>
    </div>
  )
}

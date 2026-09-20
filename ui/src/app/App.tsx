import { useState, useEffect, useMemo } from 'react'
import { Layout, Actions, Model, type TabNode } from 'flexlayout-react'
import 'flexlayout-react/style/light.css'
import { Button, Dialog, DialogTrigger, Popover } from 'react-aria-components'
import { Settings2, CloudSun, RotateCcw, ExternalLink } from 'lucide-react'
import { loadLayout, defaultLayout, layoutKey } from '../shell/layout'
import { useTheme } from '../shell/theme'
import { APPEARANCE_LIST, type AppearancePreference } from '../shell/appearances'
import { RequestPanel } from '../features/request/RequestPanel'
import { MapView } from '../features/map/MapView'
import { ResultsView } from '../features/results/ResultsView'
import { AgentPanel } from '../features/agent/AgentPanel'
import { ApiDocs } from '../features/docs/ApiDocs'
import { setToken } from '../api/client'
import { useApp } from './store'
export function App() {
  const [model, setModel] = useState(loadLayout)
  const { preference, setPreference, appearance } = useTheme()
  const [compact, setCompact] = useState(innerWidth < 950)
  const [tab, setTab] = useState('request')
  const s = useApp()
  useEffect(() => {
    const fn = () => setCompact(innerWidth < 950)
    addEventListener('resize', fn)
    return () => removeEventListener('resize', fn)
  }, [])
  const pages: Record<string, React.ReactNode> = useMemo(
    () => ({
      request: <RequestPanel />,
      map: <MapView appearance={appearance} />,
      results: <ResultsView appearance={appearance} />,
      agent: <AgentPanel />,
      docs: <ApiDocs />,
    }),
    [appearance],
  )
  function show(id: string) {
    if (compact) setTab(id)
    else model.doAction(Actions.selectTab(id))
  }
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <CloudSun size={24} />
          <strong>openepw</strong>
          <span>Weather workspace</span>
        </div>
        <nav>
          <button onClick={() => show('results')}>
            Results{s.job ? ' · ' + s.job.completed : ''}
          </button>
          <button onClick={() => show('agent')}>Agent</button>
          <button onClick={() => show('docs')}>API Docs</button>
          <a href="https://github.com/Energy-Atlas/openepw" target="_blank" rel="noreferrer">
            Source Code <ExternalLink size={12} />
          </a>
          <DialogTrigger>
            <Button aria-label="Settings">
              <Settings2 size={16} />
            </Button>
            <Popover className="settings-popover">
              <Dialog aria-label="Workspace settings">
                <h2>Appearance</h2>
                <select
                  aria-label="Appearance"
                  value={preference}
                  onChange={(e) => setPreference(e.target.value as AppearancePreference)}
                >
                  <option value="system">System</option>
                  {APPEARANCE_LIST.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label}
                    </option>
                  ))}
                </select>
                <label>
                  Session bearer token
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder="Only if backend auth is enabled"
                    onChange={(e) => setToken(e.target.value)}
                  />
                  <small>Memory only; cleared on reload.</small>
                </label>
                <button
                  onClick={() => {
                    localStorage.removeItem(layoutKey)
                    setModel(Model.fromJson(defaultLayout()))
                  }}
                >
                  <RotateCcw size={13} /> Reset layout
                </button>
              </Dialog>
            </Popover>
          </DialogTrigger>
        </nav>
      </header>
      {compact ? (
        <>
          <div className="compact-tabs">
            {Object.keys(pages).map((id) => (
              <button aria-pressed={id === tab} key={id} onClick={() => setTab(id)}>
                {id === 'docs' ? 'API Docs' : id[0].toUpperCase() + id.slice(1)}
              </button>
            ))}
          </div>
          <main className="compact-main">
            {Object.entries(pages).map(([id, page]) => (
              <div key={id} className="compact-page" hidden={id !== tab}>
                {page}
              </div>
            ))}
          </main>
        </>
      ) : (
        <main className="workspace">
          <Layout
            model={model}
            factory={(node: TabNode) =>
              pages[node.getComponent() || ''] || <p>Unknown view. Reset layout in Settings.</p>
            }
            onModelChange={(m) => localStorage.setItem(layoutKey, JSON.stringify(m.toJson()))}
          />
        </main>
      )}
      <footer>
        <span className="status-dot" /> Local workspace{' '}
        <span className="muted">Single user · scientific provenance retained</span>
        <span className="spacer" />
        <span>
          {s.busy
            ? 'Backend request in progress'
            : s.job
              ? `Job ${s.job.state.replaceAll('_', ' ')}`
              : 'Ready to plan'}
        </span>
        <span>v0.1</span>
      </footer>
    </div>
  )
}

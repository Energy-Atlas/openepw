import { useEffect, useRef } from 'react'
import { deriveWorkflow } from '../../app/workflow'
import { useApp } from '../../app/store'
import { DownloadPanel } from './DownloadPanel'
import { ExplorePanel } from './ExplorePanel'
import { ProjectPanel } from './ProjectPanel'

const descriptions = {
  explore: 'Define where and when. Preview every sampled point before discovery.',
  download: 'Select datasets for the whole query, review the live plan, and create EPWs.',
  project: 'Generate scenario-based future weather from one active validated EPW.',
}

export function StagePanel() {
  const state = useApp()
  const workflow = deriveWorkflow(state)
  const title = state.stage[0].toUpperCase() + state.stage.slice(1)
  const panel = useRef<HTMLElement>(null)
  const latestJob =
    state.stage === 'download'
      ? state.downloadJobs[0]?.id
      : state.stage === 'project'
        ? state.projectJobs[0]?.id
        : undefined
  // Each stage starts at its top, and a newly started job brings its progress into view.
  useEffect(() => {
    if (panel.current) panel.current.scrollTop = 0
  }, [state.stage, latestJob])
  return (
    <section ref={panel} className="panel stage-panel" aria-label={`${title} controls`}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">Stage controls</span>
          <h1>{title}</h1>
        </div>
        <span className={`stage-state ${workflow.stages[state.stage].stale ? 'stale' : ''}`}>
          {workflow.stages[state.stage].stale
            ? 'Needs refresh'
            : workflow.stages[state.stage].complete
              ? 'Complete'
              : 'In progress'}
        </span>
        <p>{descriptions[state.stage]}</p>
      </header>
      {state.stage === 'explore' && <ExplorePanel />}
      {state.stage === 'download' && <DownloadPanel />}
      {state.stage === 'project' && <ProjectPanel />}
      {state.error && (
        <p role="alert" className="error stage-error">
          {state.error}
        </p>
      )}
      {state.busy && <p role="status">Working with the OpenEPW service…</p>}
    </section>
  )
}

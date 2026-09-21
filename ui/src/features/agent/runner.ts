import { ACTION_REGISTRY, dispatch, type Action } from '../../app/actions'
import { useApp } from '../../app/store'
export const recipes = [
  {
    id: 'sources',
    label: 'Run this stage',
    description: 'Use the same stage-specific Run action shown in the header.',
  },
  {
    id: 'plan',
    label: 'Refresh the plan',
    description: 'Rebuild the current Download or Project plan without starting a job.',
  },
  {
    id: 'run',
    label: 'Start the reviewed job',
    description: 'Ask for confirmation, then invoke the same Run action as the header.',
  },
  {
    id: 'future',
    label: 'Plan future weather',
    description: 'Use the selected baseline and future settings.',
  },
  {
    id: 'inspect',
    label: 'Inspect selected artifact',
    description: 'Open the actual preview, QC or provenance artifact.',
  },
] as const
export async function runRecipe(
  id: string,
  send: (a: Action) => Promise<unknown> = dispatch,
  confirmed = false,
) {
  const s = useApp.getState()
  s.log('Scripted workflow: ' + id)
  if (id === 'sources') return send({ type: 'runCurrentStage' })
  if (id === 'plan') return send({ type: s.stage === 'project' ? 'planFuture' : 'planWeather' })
  if (id === 'future') return send({ type: 'planFuture' })
  if (id === 'run') {
    const action = { type: 'runCurrentStage', confirmed: true } as const
    if (!confirmed)
      return {
        requiresConfirmation: true,
        title: s.stage === 'project' ? 'Generate projections' : 'Download weather',
        description: 'This starts a server job and may invalidate downstream working state.',
        action,
        confirmation: ACTION_REGISTRY.runCurrentStage.confirmation,
      }
    return send(action)
  }
  if (id === 'inspect' && s.artifact) return send({ type: 'selectArtifact', artifact: s.artifact })
  throw Error('Select an artifact before inspecting it.')
}

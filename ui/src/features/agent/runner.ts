import { dispatch, type Action } from '../../app/actions'
import { useApp } from '../../app/store'
export const recipes = [
  {
    id: 'sources',
    label: 'Find sources',
    description: 'Discover real alternatives for the current request.',
  },
  {
    id: 'plan',
    label: 'Review a plan',
    description: 'Prepare the current request; do not submit it.',
  },
  {
    id: 'run',
    label: 'Run reviewed plan',
    description: 'Submit the exact plan currently shown in Request.',
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
export async function runRecipe(id: string, send: (a: Action) => Promise<unknown> = dispatch) {
  const s = useApp.getState()
  s.log('Scripted workflow: ' + id)
  if (id === 'sources') return send({ type: 'discover' })
  if (id === 'plan') return send({ type: s.mode === 'future' ? 'planFuture' : 'planWeather' })
  if (id === 'future') return send({ type: 'planFuture' })
  if (id === 'run') return send({ type: 'submitPlan' })
  if (id === 'inspect' && s.artifact) return send({ type: 'selectArtifact', artifact: s.artifact })
  throw Error('Select an artifact before inspecting it.')
}

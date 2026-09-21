import { ACTION_REGISTRY, dispatch, type Action } from '../../app/actions'
import { useApp } from '../../app/store'
import { APPEARANCE_LIST } from '../../shell/appearances'
import type { ResizablePanel } from '../../shell/panels'

const DEFAULT_PANEL_SIZES: Record<ResizablePanel, number> = {
  controls: 340,
  agent: 340,
  inspector: 300,
}
const PANEL_WORDS: [ResizablePanel, RegExp][] = [
  ['agent', /\bagent\b/],
  ['inspector', /\binspector\b/],
  ['controls', /\b(controls?|stage panel|left panel)\b/],
]

/**
 * Maps a typed scripted command to a recipe id. Layout and appearance commands are checked
 * first so words like "run" inside them are not mistaken for workflow commands.
 */
export function parseCommand(text: string): string | null {
  const normalized = text.trim().toLowerCase()
  if (/\b(appearance|theme|mode)\b/.test(normalized)) {
    if (/\bsystem\b/.test(normalized)) return 'appearance:system'
    // Longest labels first so "dark engineering" wins over "dark".
    const match = [...APPEARANCE_LIST]
      .sort((a, b) => b.label.length - a.label.length)
      .find((item) => normalized.includes(item.label.toLowerCase()) || normalized.includes(item.id))
    if (match) return `appearance:${match.id}`
  }
  if (/\breset\b.*\bpanels?\b|\bpanels?\b.*\breset\b/.test(normalized)) return 'reset-panels'
  const resize = /\b(wider|larger|bigger|narrower|smaller|shorter|taller)\b/.exec(normalized)
  const panel = PANEL_WORDS.find(([, pattern]) => pattern.test(normalized))?.[0]
  if (resize && panel)
    return `resize:${panel}:${['narrower', 'smaller', 'shorter'].includes(resize[1]) ? -40 : 40}`
  if (normalized.includes('inspect')) return 'inspect'
  if (normalized.includes('plan')) return 'plan'
  if (['run', 'download', 'generate'].some((word) => normalized.includes(word))) return 'run'
  if (normalized.includes('source') || normalized.includes('availability')) return 'sources'
  return null
}
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
  if (id.startsWith('appearance:'))
    return send({ type: 'setAppearance', appearance: id.slice('appearance:'.length) as never })
  if (id === 'reset-panels') {
    for (const [panel, size] of Object.entries(DEFAULT_PANEL_SIZES))
      await send({ type: 'setPanelSize', panel: panel as ResizablePanel, size })
    return
  }
  if (id.startsWith('resize:')) {
    const [, panel, delta] = id.split(':') as [string, ResizablePanel, string]
    return send({ type: 'setPanelSize', panel, size: s.panelSizes[panel] + Number(delta) })
  }
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

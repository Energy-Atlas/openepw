import type { Artifact, Job, Schemas } from '../api/client'
import { candidateDatasetSelection } from './workflow'

type RankingState = {
  weatherPlan: Schemas['WeatherPlan-Output'] | null
  discovery: Schemas['DiscoveryResult'] | null
  selectedDatasets: Schemas['DatasetSelection'][]
  selectedLocationId: string | null
}
function datasetKey(selection: Schemas['DatasetSelection'] | null | undefined) {
  return selection
    ? `${selection.provider}\u0000${selection.dataset}\u0000${selection.product_id ?? ''}`
    : ''
}

/**
 * Weather EPWs of a Download job ordered best first: EPWs at the selected point (or the first
 * planned point) come first, each location's EPWs ordered by the backend's discovery ranking.
 * EPWs that cannot be matched to the current plan keep their bundle order at the end.
 */
export function rankWeatherArtifacts(state: RankingState, job: Job): Artifact[] {
  const weather = job.bundle?.weather ?? []
  const plan = state.weatherPlan
  if (job.kind === 'future' || !plan || plan.plan_hash !== job.plan_hash) return weather
  const outputs = plan.outputs ?? []
  const outputByName = new Map(outputs.map((output) => [output.name, output]))
  const candidateById = new Map((state.discovery?.candidates ?? []).map((item) => [item.id, item]))
  const selectionOrder = new Map(
    state.selectedDatasets.map((selection, index) => [datasetKey(selection), index]),
  )
  const ranksByLocation = new Map<string, Map<string, number>>()
  for (const [locationId, ranked] of Object.entries(state.discovery?.ranked_candidate_ids ?? {})) {
    const ranks = new Map<string, number>()
    ranked.forEach((id, index) => {
      const candidate = candidateById.get(id)
      if (!candidate) return
      const key = datasetKey(
        candidateDatasetSelection(
          candidate,
          plan.request && 'product' in plan.request ? plan.request.product : undefined,
        ),
      )
      if (!ranks.has(key)) ranks.set(key, index)
    })
    ranksByLocation.set(locationId, ranks)
  }
  const locationOrder = [...new Set(outputs.map((output) => output.requested_location_id))]
  const locationIndex = new Map(locationOrder.map((id, index) => [id, index]))
  const preferred =
    state.selectedLocationId && locationOrder.includes(state.selectedLocationId)
      ? state.selectedLocationId
      : locationOrder[0]
  const scored = weather.map((artifact, index) => {
    const output = outputByName.get(artifact.path.split('/').at(-1) ?? '')
    if (!output) return { artifact, key: [2, Infinity, Infinity, Infinity, index] }
    const dataset = datasetKey(output.dataset_selection)
    const rank = ranksByLocation.get(output.requested_location_id)?.get(dataset) ?? Infinity
    const selection = selectionOrder.get(dataset) ?? Infinity
    const location = output.requested_location_id === preferred ? 0 : 1
    return {
      artifact,
      key: [
        location,
        locationIndex.get(output.requested_location_id) ?? Infinity,
        rank,
        selection,
        index,
      ],
    }
  })
  scored.sort((a, b) => {
    for (let position = 0; position < a.key.length; position++)
      if (a.key[position] !== b.key[position]) return a.key[position] - b.key[position]
    return 0
  })
  return scored.map((item) => item.artifact)
}

export function preferredWeatherArtifact(state: RankingState, job: Job): Artifact | undefined {
  return rankWeatherArtifacts(state, job)[0]
}

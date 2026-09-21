import type { Artifact, Job, Schemas } from '../api/client'

type RankingState = {
  weatherPlan: Schemas['WeatherPlan-Output'] | null
  discovery: Schemas['DiscoveryResult'] | null
  selectedDatasets: Schemas['DatasetSelection'][]
  selectedLocationId: string | null
}
type Output = NonNullable<NonNullable<RankingState['weatherPlan']>['outputs']>[number]

function sameDataset(
  candidate: Schemas['Candidate'],
  selection: Schemas['DatasetSelection'] | null | undefined,
) {
  return (
    !!selection &&
    candidate.source.provider === selection.provider &&
    candidate.source.dataset === selection.dataset &&
    (candidate.product_id ?? null) === (selection.product_id ?? null)
  )
}

/**
 * Backend rank of an output's dataset at its location: the position of the first matching
 * candidate in discovery's ranked list, then the user's selection order as a tie-break.
 */
function outputRank(state: RankingState, output: Output) {
  const ranked = state.discovery?.ranked_candidate_ids?.[output.requested_location_id] ?? []
  const candidates = new Map((state.discovery?.candidates ?? []).map((item) => [item.id, item]))
  const position = ranked.findIndex((id) => {
    const candidate = candidates.get(id)
    return candidate && sameDataset(candidate, output.dataset_selection)
  })
  const selection = state.selectedDatasets.findIndex(
    (item) =>
      item.provider === output.dataset_selection?.provider &&
      item.dataset === output.dataset_selection?.dataset &&
      (item.product_id ?? null) === (output.dataset_selection?.product_id ?? null),
  )
  return [position < 0 ? Infinity : position, selection < 0 ? Infinity : selection] as const
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
  const locationOrder = [...new Set(outputs.map((output) => output.requested_location_id))]
  const preferred =
    state.selectedLocationId && locationOrder.includes(state.selectedLocationId)
      ? state.selectedLocationId
      : locationOrder[0]
  const scored = weather.map((artifact, index) => {
    const output = outputs.find((item) => artifact.path.endsWith(item.name))
    if (!output) return { artifact, key: [2, Infinity, Infinity, Infinity, index] }
    const [rank, selection] = outputRank(state, output)
    const location = output.requested_location_id === preferred ? 0 : 1
    return {
      artifact,
      key: [location, locationOrder.indexOf(output.requested_location_id), rank, selection, index],
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

import type { Artifact, Job, Plan, Schemas } from '../api/client'

export type Stage = 'explore' | 'download' | 'project'
export type DatasetSelection = Schemas['DatasetSelection']

export type WorkflowInput = {
  stage: Stage
  requestVersion: number
  selectionVersion: number
  futureVersion: number
  discovery: Schemas['DiscoveryResult'] | null
  discoveryVersion: number | null
  selectedDatasets: DatasetSelection[]
  weatherPlan: Plan | null
  weatherPlanRequestVersion: number | null
  weatherPlanSelectionVersion: number | null
  futurePlan: Plan | null
  futurePlanVersion: number | null
  futurePlanBaselineId: string | null
  downloadJobs: Job[]
  projectJobs: Job[]
  jobs?: Job[]
  job?: Job | null
  importedArtifacts: Artifact[]
  activeWeatherArtifact: Artifact | null
  spatialPreview?: Schemas['SpatialPreview'] | null
  spatialPreviewVersion?: number | null
  busy?: boolean
}

type StageStatus = {
  unlocked: boolean
  complete: boolean
  stale: boolean
}

export type WorkflowStatus = {
  stage: Stage
  stages: Record<Stage, StageStatus>
  run: {
    action: 'discover' | 'submitWeather' | 'submitFuture'
    label: 'Find availability' | 'Download weather' | 'Generate projections'
    enabled: boolean
    reason: string | null
  }
  eligibleArtifacts: Artifact[]
  activeBaseline: Artifact | null
  download: { completed: number; failed: number }
  project: { runs: number }
}

const terminal = new Set(['completed', 'partially_completed', 'failed', 'cancelled'])

function weatherArtifacts(jobs: Job[]) {
  return jobs.flatMap((job) => job.bundle?.weather ?? [])
}

// Weather jobs from History or an earlier session are baselines too; projection outputs never are.
function historicalWeatherJobs(input: WorkflowInput) {
  return [...(input.jobs ?? []), ...(input.job ? [input.job] : [])].filter(
    (job) => job.kind === 'weather',
  )
}

function uniqueArtifacts(artifacts: Artifact[]) {
  return [...new Map(artifacts.map((artifact) => [artifact.id, artifact])).values()]
}

export function deriveWorkflow(input: WorkflowInput): WorkflowStatus {
  const discoveryCurrent =
    input.discoveryVersion === input.requestVersion && Boolean(input.discovery?.candidates.length)
  const previewCurrent =
    input.spatialPreview != null && input.spatialPreviewVersion === input.requestVersion
  const previewExecutable = input.spatialPreview?.executable !== false
  const weatherPlanCurrent =
    input.weatherPlan?.kind === 'weather' &&
    input.weatherPlanRequestVersion === input.requestVersion &&
    input.weatherPlanSelectionVersion === input.selectionVersion
  const eligibleArtifacts = uniqueArtifacts([
    ...input.importedArtifacts,
    ...weatherArtifacts(input.downloadJobs),
    ...weatherArtifacts(historicalWeatherJobs(input)),
  ]).filter((artifact) => artifact.media_type === 'application/vnd.energyplus.epw')
  const eligibleIds = new Set(eligibleArtifacts.map((artifact) => artifact.id))
  const activeBaseline =
    input.activeWeatherArtifact && eligibleIds.has(input.activeWeatherArtifact.id)
      ? input.activeWeatherArtifact
      : null
  const futurePlanCurrent =
    input.futurePlan?.kind === 'future' &&
    input.futurePlanVersion === input.futureVersion &&
    input.futurePlanBaselineId === activeBaseline?.id
  const downloadCompleted = input.downloadJobs.reduce((sum, job) => sum + job.completed, 0)
  const downloadFailed = input.downloadJobs.reduce((sum, job) => sum + job.failed, 0)
  const projectComplete = input.projectJobs.some(
    (job) => terminal.has(job.state) && Boolean(job.bundle?.weather?.length),
  )
  const downloadStale =
    Boolean(input.discovery && !discoveryCurrent) ||
    Boolean(input.weatherPlan && !weatherPlanCurrent)

  let run: WorkflowStatus['run']
  if (input.stage === 'explore') {
    const reason = !previewCurrent
      ? 'Wait for the authoritative spatial preview.'
      : !previewExecutable
        ? 'Reduce the sample count to the execution limit.'
        : input.busy
          ? 'Availability discovery is already running.'
          : null
    run = {
      action: 'discover',
      label: 'Find availability',
      enabled: reason == null,
      reason,
    }
  } else if (input.stage === 'download') {
    const reason = !discoveryCurrent
      ? 'Refresh availability after the Explore query changed.'
      : !input.selectedDatasets.length
        ? 'Select at least one dataset.'
        : !weatherPlanCurrent
          ? 'Wait for the selected-dataset plan to refresh.'
          : !input.weatherPlan?.outputs?.length
            ? 'No selected dataset can produce an EPW; review the plan issues.'
            : input.busy
              ? 'A workflow action is already running.'
              : null
    run = {
      action: 'submitWeather',
      label: 'Download weather',
      enabled: reason == null,
      reason,
    }
  } else {
    const reason = !activeBaseline
      ? 'Select a validated EPW baseline.'
      : !futurePlanCurrent
        ? 'Review a current projection plan.'
        : input.busy
          ? 'A workflow action is already running.'
          : null
    run = {
      action: 'submitFuture',
      label: 'Generate projections',
      enabled: reason == null,
      reason,
    }
  }

  return {
    stage: input.stage,
    stages: {
      explore: { unlocked: true, complete: discoveryCurrent, stale: false },
      download: {
        unlocked: Boolean(input.discovery) || input.downloadJobs.length > 0,
        complete: eligibleArtifacts.length > 0,
        stale: downloadStale,
      },
      project: {
        unlocked: eligibleArtifacts.length > 0,
        complete: projectComplete,
        stale: Boolean(input.futurePlan && !futurePlanCurrent),
      },
    },
    run,
    eligibleArtifacts,
    activeBaseline,
    download: { completed: downloadCompleted, failed: downloadFailed },
    project: { runs: input.projectJobs.length },
  }
}

export function canNavigate(status: WorkflowStatus, stage: Stage) {
  return status.stages[stage].unlocked
}

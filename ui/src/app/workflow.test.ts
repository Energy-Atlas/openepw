import { describe, expect, it } from 'vitest'
import { canNavigate, deriveWorkflow, type WorkflowInput } from './workflow'

const artifact = (id: string, role = 'weather') =>
  ({ id, role, media_type: 'application/vnd.energyplus.epw', path: `${id}.epw` }) as any

const base = (patch: Partial<WorkflowInput> = {}): WorkflowInput => ({
  stage: 'explore',
  requestVersion: 2,
  selectionVersion: 1,
  futureVersion: 3,
  discovery: null,
  discoveryVersion: null,
  selectedDatasets: [],
  weatherPlan: null,
  weatherPlanRequestVersion: null,
  weatherPlanSelectionVersion: null,
  futurePlan: null,
  futurePlanVersion: null,
  futurePlanBaselineId: null,
  downloadJobs: [],
  projectJobs: [],
  importedArtifacts: [],
  activeWeatherArtifact: null,
  ...patch,
})

describe('derived staged workflow', () => {
  it('blocks discovery until the authoritative spatial preview is current', () => {
    const missing = deriveWorkflow(base())
    expect(missing.run.enabled).toBe(false)
    expect(missing.run.reason).toMatch(/authoritative spatial preview/i)
    const ready = deriveWorkflow(
      base({
        spatialPreview: { executable: true } as any,
        spatialPreviewVersion: 2,
      }),
    )
    expect(ready.run.enabled).toBe(true)
  })

  it('unlocks Download only from usable current discovery and allows backward navigation', () => {
    const status = deriveWorkflow(
      base({
        stage: 'download',
        discovery: { candidates: [{ id: 'candidate' }] } as any,
        discoveryVersion: 2,
      }),
    )
    expect(status.stages.explore.complete).toBe(true)
    expect(status.stages.download.unlocked).toBe(true)
    expect(canNavigate(status, 'explore')).toBe(true)
  })

  it('marks upstream responses and dependent plans stale without deleting history', () => {
    const oldPlan = { kind: 'weather', plan_hash: 'old' } as any
    const status = deriveWorkflow(
      base({
        stage: 'download',
        discovery: { candidates: [{ id: 'old' }] } as any,
        discoveryVersion: 1,
        selectedDatasets: [{ provider: 'era5', dataset: 'era5' }],
        weatherPlan: oldPlan,
        weatherPlanRequestVersion: 1,
        weatherPlanSelectionVersion: 1,
      }),
    )
    expect(status.stages.download.unlocked).toBe(true)
    expect(status.stages.download.stale).toBe(true)
    expect(status.run.enabled).toBe(false)
    expect(status.run.reason).toMatch(/availability/i)
  })

  it('unlocks Project after partial Download success and retains failed counts', () => {
    const successful = artifact('weather-1')
    const status = deriveWorkflow(
      base({
        stage: 'download',
        discovery: { candidates: [{ id: 'candidate' }] } as any,
        discoveryVersion: 2,
        downloadJobs: [
          {
            id: 'job',
            state: 'partially_completed',
            total: 2,
            completed: 1,
            failed: 1,
            bundle: { weather: [successful] },
          } as any,
        ],
      }),
    )
    expect(status.stages.download.complete).toBe(true)
    expect(status.stages.project.unlocked).toBe(true)
    expect(status.download.completed).toBe(1)
    expect(status.download.failed).toBe(1)
  })

  it('treats parsed uploads as eligible baselines without claiming simulation readiness', () => {
    const upload = artifact('upload', 'baseline')
    const status = deriveWorkflow(
      base({ importedArtifacts: [upload], activeWeatherArtifact: upload }),
    )
    expect(status.stages.project.unlocked).toBe(true)
    expect(status.activeBaseline?.id).toBe('upload')
    expect(status.activeBaseline).not.toHaveProperty('simulation_ready', true)
  })

  it('keeps Project active and counts immutable reruns', () => {
    const projection = artifact('projection')
    const status = deriveWorkflow(
      base({
        stage: 'project',
        activeWeatherArtifact: artifact('baseline'),
        projectJobs: [
          { id: 'first', state: 'completed', bundle: { weather: [projection] } } as any,
          { id: 'second', state: 'failed', bundle: { weather: [] } } as any,
        ],
      }),
    )
    expect(status.stage).toBe('project')
    expect(status.project.runs).toBe(2)
    expect(status.stages.project.complete).toBe(true)
  })
})

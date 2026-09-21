import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { validateDraft } from '../api/input'
import type { Artifact, FutureRequest, Job, Plan, Schemas, WeatherRequest } from '../api/client'
import type { DatasetSelection, Stage } from './workflow'
import { isAppearanceId, type AppearancePreference } from '../shell/appearances'

export type LogEntry = { id: string; kind: 'info' | 'error' | 'tool'; text: string }
export type PanelSizes = { controls: number; agent: number; inspector: number }
export type InspectorState = {
  open: boolean
  manuallyCollapsed: boolean
  /** Heatmap variable chosen for the current artifact; cleared when the artifact changes. */
  variable?: string
}
export type PendingConfirmation = { title: string; description: string }
export type PlanKind = 'weather' | 'future'

export type State = {
  stage: Stage
  mode: 'weather' | 'future'
  draft: WeatherRequest
  future: FutureRequest
  version: number
  requestVersion: number
  selectionVersion: number
  futureVersion: number
  spatialPreview: Schemas['SpatialPreview'] | null
  spatialPreviewVersion: number | null
  spatialPreviewAttemptVersion: number | null
  discovery: Schemas['DiscoveryResult'] | null
  discoveryVersion: number | null
  selectedDatasets: DatasetSelection[]
  weatherPlan: Plan | null
  weatherPlanRequestVersion: number | null
  weatherPlanSelectionVersion: number | null
  futurePlan: Plan | null
  futurePlanVersion: number | null
  futurePlanBaselineId: string | null
  plan: Plan | null
  job: Job | null
  jobs: Job[]
  downloadJobs: Job[]
  projectJobs: Job[]
  cursor: string | null
  artifact: Artifact | null
  activeWeatherArtifact: Artifact | null
  baselineOrigin: 'download' | 'upload' | null
  importedArtifacts: Artifact[]
  preview: Schemas['WeatherPreview'] | null
  visualization: Schemas['WeatherVisualization'] | null
  detail: unknown
  coverageLayers: Schemas['CoverageLayer'][]
  selectedCoverageIds: string[]
  inspector: InspectorState
  pendingConfirmation: PendingConfirmation | null
  panelSizes: PanelSizes
  appearance: AppearancePreference
  /** Sample point whose details were opened on the map; ranks which EPW opens first. */
  selectedLocationId: string | null
  busy: boolean
  error: string
  logs: LogEntry[]
  // Idempotency keys and submission state are per plan kind so Download and Project never
  // share a key or block each other.
  submitKeys: Record<PlanKind, string | null>
  submitted: Record<PlanKind, boolean>
  edit: (patch: Partial<WeatherRequest>) => void
  editFuture: (patch: Partial<FutureRequest>) => void
  selectDatasets: (selections: DatasetSelection[]) => void
  setStage: (stage: Stage) => void
  setMode: (mode: 'weather' | 'future') => void
  setInspectorOpen: (open: boolean, manually?: boolean) => void
  log: (text: string, kind?: LogEntry['kind']) => void
}

const defaultDraft: WeatherRequest = {
  schema_version: '0.1',
  missing_policy: 'warn',
  skip_feb_29: false,
  locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 },
  years: [2024],
  providers: [],
  dataset_selections: [],
  product: 'amy',
}

const defaultFuture: FutureRequest = {
  schema_version: '0.1',
  baseline: '',
  method: 'morph',
  target_year: 2050,
  reference_period: [1985, 2014],
  climate_scenario: 'ssp245',
  profile: 'typical',
}

function resetSubmission(state: State, kinds: PlanKind[]) {
  const submitKeys = { ...state.submitKeys }
  const submitted = { ...state.submitted }
  for (const kind of kinds) {
    submitKeys[kind] = null
    submitted[kind] = false
  }
  return { submitKeys, submitted }
}

export function validAppearance(value: unknown): AppearancePreference | null {
  return value === 'system' || (typeof value === 'string' && isAppearanceId(value)) ? value : null
}

// Appearance used to live under its own key; carry it over once into the persisted store.
const LEGACY_APPEARANCE_KEY = 'openepw.appearance.v1'
function legacyAppearance(): AppearancePreference {
  try {
    return validAppearance(localStorage.getItem(LEGACY_APPEARANCE_KEY)) ?? 'system'
  } catch {
    return 'system'
  }
}

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      stage: 'explore',
      mode: 'weather',
      draft: defaultDraft,
      future: defaultFuture,
      version: 0,
      requestVersion: 0,
      selectionVersion: 0,
      futureVersion: 0,
      spatialPreview: null,
      spatialPreviewVersion: null,
      spatialPreviewAttemptVersion: null,
      discovery: null,
      discoveryVersion: null,
      selectedDatasets: [],
      weatherPlan: null,
      weatherPlanRequestVersion: null,
      weatherPlanSelectionVersion: null,
      futurePlan: null,
      futurePlanVersion: null,
      futurePlanBaselineId: null,
      plan: null,
      job: null,
      jobs: [],
      downloadJobs: [],
      projectJobs: [],
      cursor: null,
      artifact: null,
      activeWeatherArtifact: null,
      baselineOrigin: null,
      importedArtifacts: [],
      preview: null,
      visualization: null,
      detail: null,
      coverageLayers: [],
      selectedCoverageIds: [],
      inspector: { open: false, manuallyCollapsed: false },
      pendingConfirmation: null,
      panelSizes: { controls: 340, agent: 340, inspector: 300 },
      appearance: legacyAppearance(),
      selectedLocationId: null,
      busy: false,
      error: '',
      logs: [],
      submitKeys: { weather: null, future: null },
      submitted: { weather: false, future: false },
      edit: (patch) =>
        set((state) => {
          const clearBaseline = state.baselineOrigin === 'download'
          return {
            draft: { ...state.draft, ...patch },
            version: state.version + 1,
            requestVersion: state.requestVersion + 1,
            selectedLocationId: null,
            ...resetSubmission(state, clearBaseline ? ['weather', 'future'] : ['weather']),
            activeWeatherArtifact: clearBaseline ? null : state.activeWeatherArtifact,
            baselineOrigin: clearBaseline ? null : state.baselineOrigin,
            future: clearBaseline ? { ...state.future, baseline: '' } : state.future,
            futureVersion: clearBaseline ? state.futureVersion + 1 : state.futureVersion,
          }
        }),
      editFuture: (patch) =>
        set((state) => ({
          future: { ...state.future, ...patch },
          version: state.version + 1,
          futureVersion: state.futureVersion + 1,
          ...resetSubmission(state, ['future']),
        })),
      selectDatasets: (selections) =>
        set((state) => {
          const clearBaseline = state.baselineOrigin === 'download'
          return {
            selectedDatasets: selections,
            draft: { ...state.draft, dataset_selections: selections },
            version: state.version + 1,
            selectionVersion: state.selectionVersion + 1,
            ...resetSubmission(state, clearBaseline ? ['weather', 'future'] : ['weather']),
            activeWeatherArtifact: clearBaseline ? null : state.activeWeatherArtifact,
            baselineOrigin: clearBaseline ? null : state.baselineOrigin,
            future: clearBaseline ? { ...state.future, baseline: '' } : state.future,
            futureVersion: clearBaseline ? state.futureVersion + 1 : state.futureVersion,
          }
        }),
      setStage: (stage) => set({ stage, mode: stage === 'project' ? 'future' : 'weather' }),
      setMode: (mode) =>
        set((state) => ({
          mode,
          stage:
            mode === 'future' ? 'project' : state.stage === 'project' ? 'download' : state.stage,
          plan: mode === 'future' ? state.futurePlan : state.weatherPlan,
        })),
      setInspectorOpen: (open, manually = false) =>
        set((state) => ({
          inspector: {
            open,
            manuallyCollapsed:
              manually && !open ? true : open ? false : state.inspector.manuallyCollapsed,
          },
        })),
      log: (text, kind = 'info') =>
        set({ logs: [...get().logs, { id: crypto.randomUUID(), text, kind }].slice(-100) }),
    }),
    {
      name: 'openepw.draft.v2',
      version: 2,
      partialize: (state) => ({
        draft: state.draft,
        future: state.future,
        stage: state.stage,
        selectedCoverageIds: state.selectedCoverageIds,
        panelSizes: state.panelSizes,
        appearance: state.appearance,
      }),
      merge: (saved, current) => {
        try {
          const value = saved as Partial<State>
          const appearance = validAppearance(value.appearance) ?? current.appearance
          current = { ...current, appearance }
          validateDraft(value.draft)
          if (
            !value.future ||
            !['morph', 'climate_profile'].includes(value.future.method) ||
            typeof value.future.baseline !== 'string'
          )
            return current
          const stage = ['explore', 'download', 'project'].includes(value.stage ?? '')
            ? value.stage!
            : 'explore'
          return {
            ...current,
            draft: value.draft,
            future: { ...current.future, ...value.future },
            stage,
            mode: stage === 'project' ? 'future' : 'weather',
            selectedCoverageIds: value.selectedCoverageIds ?? [],
            panelSizes: { ...current.panelSizes, ...value.panelSizes },
          }
        } catch {
          return current
        }
      },
    },
  ),
)

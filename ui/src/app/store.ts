import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { validateDraft } from '../api/input'
import type { WeatherRequest, FutureRequest, Plan, Job, Artifact, Schemas } from '../api/client'
export type LogEntry = { id: string; kind: 'info' | 'error' | 'tool'; text: string }
type State = {
  mode: 'weather' | 'future'
  draft: WeatherRequest
  future: FutureRequest
  version: number
  plan: Plan | null
  discovery: Schemas['DiscoveryResult'] | null
  job: Job | null
  jobs: Job[]
  cursor: string | null
  artifact: Artifact | null
  preview: Schemas['WeatherPreview'] | null
  detail: unknown
  busy: boolean
  error: string
  logs: LogEntry[]
  submitKey: string | null
  submitted: boolean
  edit: (patch: Partial<WeatherRequest>) => void
  editFuture: (patch: Partial<FutureRequest>) => void
  setMode: (mode: 'weather' | 'future') => void
  log: (text: string, kind?: LogEntry['kind']) => void
}
export const useApp = create<State>()(
  persist(
    (set, get) => ({
      mode: 'weather',
      draft: {
        schema_version: '0.1',
        missing_policy: 'warn',
        leap_policy: 'preserve',
        locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 },
        years: [2024],
        providers: ['openmeteo'],
        product: 'amy',
      },
      future: {
        schema_version: '0.1',
        baseline: '',
        method: 'morph',
        target_year: 2050,
        reference_period: [1985, 2014],
        climate_scenario: 'ssp245',
        profile: 'typical',
      },
      version: 0,
      plan: null,
      discovery: null,
      job: null,
      jobs: [],
      cursor: null,
      artifact: null,
      preview: null,
      detail: null,
      busy: false,
      error: '',
      logs: [],
      submitKey: null,
      submitted: false,
      edit: (patch) =>
        set((s) => ({
          draft: { ...s.draft, ...patch },
          version: s.version + 1,
          plan: null,
          discovery: null,
          submitKey: null,
          submitted: false,
        })),
      editFuture: (patch) =>
        set((s) => ({
          future: { ...s.future, ...patch },
          version: s.version + 1,
          plan: null,
          submitKey: null,
          submitted: false,
        })),
      setMode: (mode) =>
        set((s) => ({
          mode,
          version: s.version + 1,
          plan: null,
          submitKey: null,
          submitted: false,
        })),
      log: (text, kind = 'info') =>
        set({ logs: [...get().logs, { id: crypto.randomUUID(), text, kind }].slice(-100) }),
    }),
    {
      name: 'openepw.draft.v1',
      version: 1,
      partialize: (s) => ({ draft: s.draft, future: s.future, mode: s.mode }),
      merge: (saved, current) => {
        try {
          const value = saved as Partial<State>
          validateDraft(value.draft)
          if (
            !value.future ||
            !['morph', 'climate_profile'].includes(value.future.method) ||
            typeof value.future.baseline !== 'string'
          )
            return current
          return {
            ...current,
            draft: value.draft,
            future: { ...current.future, ...value.future },
            mode: value.mode === 'future' ? 'future' : 'weather',
          }
        } catch {
          return current
        }
      },
    },
  ),
)

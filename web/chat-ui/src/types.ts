export type ChatEvent = {
  id: number
  type: 'message' | 'question' | 'tool' | 'plan' | 'job' | 'artifacts' | 'view' | 'error'
  text?: string
  data?: Record<string, unknown>
}

export type ChatCard = {
  id: string
  revision: number
  kind: 'choice' | 'text' | 'map' | 'plan_review'
  prompt: string
  options?: Array<{ id: string; label: string }>
  data?: Record<string, unknown>
}

export type SessionSnapshot = {
  id: string
  revision: number
  facts: Record<string, unknown>
  events: ChatEvent[]
  active_card: ChatCard | null
  job_id?: string | null
  job_ids?: string[]
  plan_hash?: string | null
  view_ids?: string[]
}

export type JobSnapshot = {
  id: string
  state: string
  total: number
  completed: number
  failed: number
  bundle?: { weather?: Array<{ id: string; role: string; path: string }>;
    manifest?: { id: string } } | null
}

export type JobManifest = {
  simulation_ready?: boolean
  batch_rows: Array<{ artifact_id?: string | null; output_id?: string | null;
    occurrence_index: number; period_start?: string | null; period_end?: string | null;
    status: string; dataset_selection?: { provider: string; dataset: string }; issue_codes?: string[] }>
  output_mapping: Array<{ id: string; name: string; occurrence_index: number }>
}

export type ViewSpec = {
  schema_version: string
  family: string
  data_ref: { view_id: string; shape: 'rows' | 'points' | 'matrix'; total_rows: number }
  encodings: Record<string, unknown>
  sources: Array<Record<string, unknown>>
  quality: { expected_hours: number; valid_hours: number; missing_hours: number }
  summary: string
}

export type ViewPage = {
  schema_version: string
  view_id: string
  rows: Array<Record<string, unknown>>
  total_rows: number
  next_offset: number | null
  specs?: ViewSpec[]
  warnings?: Array<{ code: string }>
}

export type AvailabilitySummary = {
  checked_at: string
  snapshots: Array<{ generation_id: string; created_at: string }>
  options: Array<{ provider: string; dataset: string; footprint?: [number,number,number,number] | null;
    status: string; access: string; health: string; evidence_ids: string[]; evidence_bases: string[];
    unknowns: string[]; reasons: string[]; rank?: number | null; occurrence_index: number }>
  issues: Array<{ code: string; message: string }>
}

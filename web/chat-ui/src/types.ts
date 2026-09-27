export type ChatEvent = {
  id: number
  type: 'message' | 'question' | 'tool' | 'plan' | 'job' | 'artifacts' | 'view' | 'error'
  text?: string
  data?: Record<string, unknown>
}

export type ChatCard = {
  id: string
  revision: number
  kind: 'choice' | 'text' | 'map' | 'plan_review' | 'location_review'
  prompt: string
  options?: Array<{ id: string; label: string; detail?: string }>
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
    occurrence_index: number; requested_location_id?: string;
    period_start?: string | null; period_end?: string | null;
    status: string; dataset_selection?: { provider: string; dataset: string }; issue_codes?: string[];
    metadata?: { requested_location?: { lat: number; lon: number } } }>
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

export type CatalogScopes = {
  snapshot: { generation_id: string; created_at: string } | null
  scopes: Array<{ provider: string; dataset: string; footprint: [number, number, number, number];
    longitude_convention: '-180_180' | '0_360' | null; evidence_bases: string[];
    evidence_dates: string[] }>
  unmapped: Array<{ provider: string; dataset: string }>
}

export type CatalogLayer = {
  id: string
  kind: 'stations' | 'sites' | 'cells' | 'area' | 'extent'
  label: string
  caveat: string
  count: number
  evidence_dates: string[]
  points?: Array<[number, number, string, unknown, ...unknown[]]>
  rects?: Array<[number, number, number, number]>
  polygon?: Array<[number, number]>
  probes?: Array<[number, number]>
  bounds?: [number, number, number, number]
  members?: string[]
  omitted?: Record<string, number>
  source_url?: string
}

export type CatalogMap = {
  schema: string
  snapshot: { generation_id: string; created_at: string } | null
  layers: CatalogLayer[]
  unmapped: Array<{ provider: string; dataset: string; reason: string }>
}

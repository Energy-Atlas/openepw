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
  plan_hash?: string | null
  view_ids?: string[]
}

export type JobSnapshot = {
  id: string
  state: string
  total: number
  completed: number
  failed: number
  bundle?: { weather?: Array<{ id: string; role: string; path: string }> } | null
}

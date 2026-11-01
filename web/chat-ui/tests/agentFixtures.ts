import { screen, waitFor } from '@testing-library/react'
import { expect, vi } from 'vitest'
import type { ChatApi } from '../src/api'
import type { AgentEvent, AgentForm, AgentSnapshot, FormKind } from '../src/types'
import forms from './fixtures/agent-forms.json'

/** Real /v2 snapshots, one per form kind, written by tests/agent/test_web_fixtures.py. */
export const FIXTURES = forms as unknown as Record<FormKind, AgentSnapshot>

export function form(kind: FormKind, prompt: string, extra: Partial<AgentForm> = {}): AgentForm {
  return { id: `form-${kind}`, revision: 3, kind, gate: null, prompt, summary: '', options: [], multi: false,
    data: {}, allow_text: true, ...extra }
}

export function snapshot(open: AgentForm | null, extra: Partial<AgentSnapshot> = {}): AgentSnapshot {
  return { id: 'session-1', mode: 'guided', revision: open?.revision ?? 1, form: open, busy: false, ended: false,
    downgraded: false, model_available: true, profile: 'hosted', strikes: 0, strike_limit: 3, events: [],
    cursor: 0, parts: [], places: [], years: [], job_ids: [], finished_job_ids: [], artifact_ids: [],
    candidates: [], offers: [], ...extra }
}

export function event(seq: number, type: AgentEvent['type'], text: string, data: Record<string, unknown> = {}): AgentEvent {
  return { seq, type, text, data }
}

/** A client for one snapshot; `input` answers with the same snapshot unless replaced. */
export function fakeApi(state: AgentSnapshot, extra: Record<string, unknown> = {}) {
  const api = {
    create: vi.fn(async () => state), get: vi.fn(async () => state), input: vi.fn(async () => state),
    catalogMap: async () => ({ schema: 'catalog-map-1', snapshot: null, layers: [], unmapped: [] }),
    artifactUrl: (id: string) => `/v1/artifacts/${id}`,
    calls: [], ...extra,
  }
  return api as typeof api & ChatApi
}

/** The message field once a session is open (before that it shows disabled). */
export function messageField(): Promise<HTMLElement> {
  return waitFor(() => {
    const field = screen.getByRole('textbox', { name: 'Message' })
    expect(field).toBeEnabled()
    return field
  })
}

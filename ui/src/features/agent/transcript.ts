import type { LogEntry } from '../../app/store'

export type TranscriptItem =
  | { kind: 'call'; id: string; call: LogEntry; results: LogEntry[] }
  | { kind: 'note'; id: string; entry: LogEntry }

/** Groups each tool call with the observations that follow it into one expandable card. */
export function groupTranscript(logs: LogEntry[]): TranscriptItem[] {
  const items: TranscriptItem[] = []
  for (const entry of logs) {
    const last = items.at(-1)
    if (entry.kind === 'tool') items.push({ kind: 'call', id: entry.id, call: entry, results: [] })
    else if (last?.kind === 'call') last.results.push(entry)
    else items.push({ kind: 'note', id: entry.id, entry })
  }
  return items
}

export function callStatus(item: Extract<TranscriptItem, { kind: 'call' }>) {
  if (item.results.some((result) => result.kind === 'error')) return 'failed'
  return item.results.length ? 'done' : 'running'
}

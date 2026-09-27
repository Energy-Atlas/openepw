import type { ChatEvent } from './types'

export type TranscriptItem =
  | { kind: 'event'; event: ChatEvent }
  | { kind: 'tool'; id: number; tool: string; action: string; result?: string }

/** Tool calls render as one line each; a result joins the call it answers. */
export function transcriptItems(events: ChatEvent[]): TranscriptItem[] {
  const items: TranscriptItem[] = []
  for (const event of events) {
    if (event.type !== 'tool') { items.push({ kind: 'event', event }); continue }
    const tool = String(event.data?.tool ?? 'service')
    const last = items.at(-1)
    if (event.data?.phase === 'result' && last?.kind === 'tool' && last.tool === tool && last.result === undefined) {
      last.result = event.text
      continue
    }
    items.push({ kind: 'tool', id: event.id, tool, action: event.text ?? tool })
  }
  return items
}

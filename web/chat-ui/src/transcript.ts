import type { AgentEvent } from './types'

export type TranscriptItem =
  | { kind: 'event'; event: AgentEvent }
  | { kind: 'tool'; id: number; tool: string; action: string; result?: string }

/** Tool calls render as one line each; a result joins the call it answers. Form events are left
 * out: the open form is shown in the dock and earlier answers appear as the person's turns. */
export function transcriptItems(events: AgentEvent[]): TranscriptItem[] {
  const items: TranscriptItem[] = []
  for (const event of events) {
    if (event.type === 'form') continue
    if (event.type !== 'tool') { items.push({ kind: 'event', event }); continue }
    const tool = String(event.data?.tool ?? 'service')
    const last = items.at(-1)
    if (event.data?.phase === 'result' && last?.kind === 'tool' && last.tool === tool && last.result === undefined) {
      last.result = event.text.split('\n')[0]
      continue
    }
    items.push({ kind: 'tool', id: event.seq, tool, action: toolAction(tool) })
  }
  return items
}

const ACTIONS: Record<string, string> = {
  weather_geocode: 'Finding the place', weather_places_preview: 'Reading the places',
  weather_places_interpret: 'Reading the places', weather_place_set: 'Listing places',
  weather_locations_review: 'Checking the locations and time offsets', weather_product_offers: 'Checking which products are offered',
  weather_assess: 'Checking availability', weather_plan: 'Planning the weather files', weather_submit: 'Starting retrieval',
  job_inspect: 'Checking the job', artifact_inspect: 'Checking the EPW', weather_visualize: 'Preparing a chart',
  weather_export_compact: 'Packing a ZIP', epw_upload: 'Registering the EPW',
  job_outputs: 'Reading your files', list_outputs: 'Listing your files', offer_download: 'Offering downloads',
  job_retry_failed: 'Retrying the failed outputs',
}

/** A tool step in words, for the transcript. */
export function toolAction(tool: string): string {
  return ACTIONS[tool] ?? tool.replace(/_/g, ' ')
}

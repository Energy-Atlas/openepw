import type { JobManifest, JobSnapshot } from './types'

export function mergeJobManifests(entries: Array<{ job: JobSnapshot; manifest: JobManifest | null }>) {
  const weather = new Map(entries.flatMap(({ job }) => (job.bundle?.weather ?? []).map(ref => [ref.id, ref] as const)))
  const rows = new Map<string, JobManifest['batch_rows'][number]>()
  for (const { manifest } of entries) {
    for (const row of manifest?.batch_rows ?? []) {
      const key = row.output_id ?? `${row.occurrence_index}:${row.dataset_selection?.provider}:${row.period_start}`
      const previous = rows.get(key)
      if (!previous || row.status === 'succeeded' || previous.status !== 'succeeded') rows.set(key, row)
    }
  }
  const merged = [...rows.values()]
  const artifactIds = [...new Set(merged.filter(row => row.status === 'succeeded' && row.artifact_id &&
    weather.has(row.artifact_id)).map(row => row.artifact_id!))]
  return { rows: merged, artifactIds, complete: entries.every(item => Boolean(item.manifest)) }
}

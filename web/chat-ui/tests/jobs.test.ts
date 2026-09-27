import { describe, expect, it } from 'vitest'
import { mergeJobManifests } from '../src/jobs'
import type { JobManifest, JobSnapshot } from '../src/types'

const row = (output_id: string, status: string, artifact_id?: string) => ({
  output_id, status, artifact_id, occurrence_index: 0, period_start: '2018-01-01',
  dataset_selection: { provider: 'openmeteo', dataset: 'era5' },
})
const job = (id: string, artifact_ids: string[]): JobSnapshot => ({
  id, state: 'completed', total: 1, completed: 1, failed: 0,
  bundle: { weather: artifact_ids.map(artifact_id => ({ id: artifact_id, role: 'weather', path: `${artifact_id}.epw` })) },
})
const manifest = (...rows: JobManifest['batch_rows']): JobManifest => ({ batch_rows: rows, output_mapping: [] })

describe('retry manifest identity', () => {
  it('keeps original successes and replaces retried failures', () => {
    const merged = mergeJobManifests([
      { job: job('first', ['a']), manifest: manifest(row('one', 'succeeded', 'a'), row('two', 'failed')) },
      { job: job('retry', ['b']), manifest: manifest(row('two', 'succeeded', 'b')) },
    ])
    expect(merged.artifactIds).toEqual(['a', 'b'])
    expect(merged.rows.map(item => item.status)).toEqual(['succeeded', 'succeeded'])
  })

  it('never offers an unmapped artifact when a manifest is missing', () => {
    const merged = mergeJobManifests([{ job: job('first', ['a']), manifest: null }])
    expect(merged.complete).toBe(false)
    expect(merged.artifactIds).toEqual([])
  })
})

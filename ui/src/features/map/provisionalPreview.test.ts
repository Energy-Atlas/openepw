import { afterEach, expect, it, vi } from 'vitest'
import { useApp } from '../../app/store'
import { deriveWorkflow } from '../../app/workflow'
import { createPreviewScheduler, provisionalRequest } from './provisionalPreview'
import type { Position } from './selection'

afterEach(() => vi.useRealTimers())

const draft = {
  schema_version: '0.1',
  locations: { lat: 42, lon: -76, standard_offset_minutes: 0 },
  years: [2024],
  product: 'amy',
  dataset_selections: [{ provider: 'old', dataset: 'choice' }],
} as any
const triangle: Position[] = [
  [0, 0],
  [1, 0],
  [1, 1],
]
const preview = (total: number) => ({ total_count: total, executable: true, locations: [] }) as any

it('requests provisional previews only for complete area shapes, without old selections', () => {
  expect(provisionalRequest(draft, 'polygon', triangle.slice(0, 2))).toBeNull()
  expect(provisionalRequest(draft, 'points', triangle)).toBeNull()
  expect(provisionalRequest(draft, 'point', triangle.slice(0, 1))).toBeNull()
  const request = provisionalRequest(draft, 'polygon', triangle)!
  expect(request.dataset_selections).toEqual([])
  expect(request.locations).toMatchObject({ type: 'Polygon' })
  expect(request.years).toEqual([2024])
  expect(provisionalRequest(draft, 'bbox', triangle.slice(0, 2))?.locations).toEqual({
    west: 0,
    south: 0,
    east: 1,
    north: 0,
  })
})

it('waits for edits to settle and sends only the latest shape', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockResolvedValue(preview(12))
  const onResult = vi.fn()
  const scheduler = createPreviewScheduler({ fetch, onResult })
  const first = provisionalRequest(draft, 'polygon', triangle)
  const second = provisionalRequest(draft, 'polygon', [...triangle, [0, 1]])
  scheduler.schedule(first)
  await vi.advanceTimersByTimeAsync(300)
  scheduler.schedule(second)
  scheduler.schedule(second)
  await vi.advanceTimersByTimeAsync(599)
  expect(fetch).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toBe(second)
  expect(onResult).toHaveBeenCalledWith(preview(12))
})

it('aborts a superseded request and ignores its late result', async () => {
  vi.useFakeTimers()
  const resolvers: ((value: unknown) => void)[] = []
  const signals: AbortSignal[] = []
  const fetch = vi.fn((_request, signal: AbortSignal) => {
    signals.push(signal)
    return new Promise<any>((resolve) => resolvers.push(resolve))
  })
  const onResult = vi.fn()
  const scheduler = createPreviewScheduler({ fetch, onResult })
  scheduler.schedule(provisionalRequest(draft, 'polygon', triangle))
  await vi.advanceTimersByTimeAsync(600)
  scheduler.schedule(provisionalRequest(draft, 'polygon', [...triangle, [0, 1]]))
  expect(signals[0].aborted).toBe(true)
  resolvers[0](preview(99))
  await vi.advanceTimersByTimeAsync(600)
  resolvers[1](preview(7))
  await vi.advanceTimersByTimeAsync(0)
  expect(onResult.mock.calls.map((call) => call[0]?.total_count)).toEqual([7])
})

it('clears the estimate when the shape becomes incomplete and never touches workflow state', async () => {
  vi.useFakeTimers()
  useApp.setState({
    stage: 'explore',
    spatialPreview: { executable: true } as any,
    spatialPreviewVersion: 3,
    requestVersion: 4,
  })
  const before = deriveWorkflow(useApp.getState()).run
  const onResult = vi.fn()
  const scheduler = createPreviewScheduler({
    fetch: vi.fn().mockResolvedValue(preview(5)),
    onResult,
  })
  scheduler.schedule(provisionalRequest(draft, 'polygon', triangle))
  await vi.advanceTimersByTimeAsync(600)
  scheduler.schedule(null)
  expect(onResult.mock.calls.map((call) => call[0]?.total_count ?? null)).toEqual([5, null])
  expect(useApp.getState().spatialPreviewVersion).toBe(3)
  expect(deriveWorkflow(useApp.getState()).run).toEqual(before)
  expect(before.enabled).toBe(false)
})

import { rememberIntent } from './intent'
import { it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api/client'
import { dispatch } from './actions'
import { useApp } from './store'
beforeEach(() => {
  useApp.getState().edit({ years: [2024] })
  vi.restoreAllMocks()
  localStorage.clear()
})
it('ignores a discovery result after request edits', async () => {
  let resolve!: (v: any) => void
  vi.spyOn(api, 'discover').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'discover' })
  useApp.getState().edit({ years: [2023] })
  resolve({ locations: [], candidates: [], issues: [] })
  await pending
  expect(useApp.getState().discovery).toBeNull()
})
it('invalidates the reviewed plan on draft edits', () => {
  useApp.setState({ plan: { plan_hash: 'old' } as any })
  useApp.getState().edit({ years: [2022] })
  expect(useApp.getState().plan).toBeNull()
})

it('reuses a submit idempotency key after a lost response', async () => {
  const plan = { kind: 'weather', plan_hash: 'plan' } as any
  useApp.setState({ plan, submitKey: 'same-intent', submitted: false })
  const submit = vi
    .spyOn(api, 'submit')
    .mockRejectedValueOnce(new Error('connection lost'))
    .mockResolvedValueOnce({ id: 'job', state: 'queued' } as any)
  await expect(dispatch({ type: 'submitPlan' })).rejects.toThrow()
  await dispatch({ type: 'submitPlan' })
  expect(submit.mock.calls.map((c) => c[1])).toEqual(['same-intent', 'same-intent'])
})
it('keeps an edited request unsubmitted after an older submission returns', async () => {
  useApp.setState({ plan: { kind: 'weather' } as any, submitKey: 'old', submitted: false })
  let resolve!: (v: any) => void
  vi.spyOn(api, 'submit').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'submitPlan' })
  useApp.getState().edit({ years: [2021] })
  resolve({ id: 'job', state: 'queued' })
  await pending
  expect(useApp.getState().submitted).toBe(false)
})
it('selecting another job clears the previous artifact preview', async () => {
  useApp.setState({ artifact: { id: 'old' } as any, preview: { total_rows: 24 } as any })
  vi.spyOn(api, 'job').mockResolvedValue({ id: 'new', state: 'completed' } as any)
  await dispatch({ type: 'selectJob', id: 'new' })
  expect(useApp.getState().artifact).toBeNull()
  expect(useApp.getState().preview).toBeNull()
})

it('submitting a new job clears old inspection state', async () => {
  useApp.setState({
    plan: { kind: 'weather' } as any,
    submitted: false,
    artifact: { id: 'old' } as any,
    preview: {} as any,
    detail: { old: true },
  })
  vi.spyOn(api, 'submit').mockResolvedValue({ id: 'new', state: 'queued' } as any)
  await dispatch({ type: 'submitPlan' })
  expect(useApp.getState().artifact).toBeNull()
  expect(useApp.getState().preview).toBeNull()
  expect(useApp.getState().detail).toBeNull()
})
it('stopping an upload suppresses a late completion', async () => {
  let resolve!: (v: any) => void
  const baseline = useApp.getState().future.baseline
  vi.spyOn(api, 'upload').mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const pending = dispatch({ type: 'uploadBaseline', file: new File(['data'], 'test.epw') })
  await dispatch({ type: 'cancelActive' })
  resolve({ id: 'late' })
  await expect(pending).rejects.toThrow()
  expect(useApp.getState().future.baseline).toBe(baseline)
  expect(useApp.getState().busy).toBe(false)
})

it('replanning after reload reuses persisted submission intent', async () => {
  rememberIntent('same-plan', 'before-reload')
  vi.spyOn(api, 'plan').mockResolvedValue({ kind: 'weather', plan_hash: 'same-plan' } as any)
  await dispatch({ type: 'planWeather' })
  expect(useApp.getState().submitKey).toBe('before-reload')
  expect(useApp.getState().submitted).toBe(false)
})

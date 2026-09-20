import { it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api/client'
import { dispatch } from './actions'
import { useApp } from './store'
beforeEach(() => {
  useApp.getState().edit({ years: [2024] })
  vi.restoreAllMocks()
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

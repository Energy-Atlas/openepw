import { it, expect, vi } from 'vitest'
import { runRecipe } from './runner'
import { useApp } from '../../app/store'
it('routes scripts through the same actions, without synthetic success', async () => {
  const send = vi.fn().mockResolvedValue({})
  useApp.setState({ mode: 'weather' })
  await runRecipe('sources', send)
  await runRecipe('plan', send)
  await runRecipe('run', send)
  await runRecipe('future', send)
  expect(send.mock.calls.map((c) => c[0].type)).toEqual([
    'discover',
    'planWeather',
    'submitPlan',
    'planFuture',
  ])
})
it('propagates a real tool failure', async () => {
  await expect(
    runRecipe('sources', vi.fn().mockRejectedValue(new Error('provider unavailable'))),
  ).rejects.toThrow('provider unavailable')
})

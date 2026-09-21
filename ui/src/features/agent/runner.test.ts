import { it, expect, vi } from 'vitest'
import { runRecipe } from './runner'
import { useApp } from '../../app/store'
it('routes scripts through the same actions, without synthetic success', async () => {
  const send = vi.fn().mockResolvedValue({})
  useApp.setState({ stage: 'explore' })
  await runRecipe('sources', send)
  useApp.setState({ stage: 'download' })
  await runRecipe('plan', send)
  const confirmation = await runRecipe('run', send)
  await runRecipe('run', send, true)
  useApp.setState({ stage: 'project' })
  await runRecipe('future', send)
  expect(send.mock.calls.map((c) => c[0].type)).toEqual([
    'runCurrentStage',
    'planWeather',
    'runCurrentStage',
    'planFuture',
  ])
  expect(confirmation).toMatchObject({ requiresConfirmation: true })
  expect(send.mock.calls[2][0]).toMatchObject({ confirmed: true })
})
it('propagates a real tool failure', async () => {
  await expect(
    runRecipe('sources', vi.fn().mockRejectedValue(new Error('provider unavailable'))),
  ).rejects.toThrow('provider unavailable')
})

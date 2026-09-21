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

it('parses layout and appearance commands before workflow words', async () => {
  const { parseCommand } = await import('./runner')
  expect(parseCommand('Use the dark engineering theme')).toBe('appearance:darkEngineering')
  expect(parseCommand('dark appearance')).toBe('appearance:dark')
  expect(parseCommand('switch to system mode')).toBe('appearance:system')
  expect(parseCommand('make the agent panel wider')).toBe('resize:agent:40')
  expect(parseCommand('narrower controls')).toBe('resize:controls:-40')
  expect(parseCommand('taller inspector')).toBe('resize:inspector:40')
  expect(parseCommand('reset panels')).toBe('reset-panels')
  expect(parseCommand('refresh the plan')).toBe('plan')
  expect(parseCommand('hello there')).toBeNull()
})

it('routes appearance and panel recipes through the shared registry actions', async () => {
  const send = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ panelSizes: { controls: 300, agent: 360, inspector: 250 } })
  await runRecipe('appearance:dark', send)
  await runRecipe('resize:agent:40', send)
  await runRecipe('reset-panels', send)
  expect(send.mock.calls.map((call) => call[0])).toEqual([
    { type: 'setAppearance', appearance: 'dark' },
    { type: 'setPanelSize', panel: 'agent', size: 400 },
    { type: 'setPanelSize', panel: 'controls', size: 340 },
    { type: 'setPanelSize', panel: 'agent', size: 340 },
    { type: 'setPanelSize', panel: 'inspector', size: 300 },
  ])
})

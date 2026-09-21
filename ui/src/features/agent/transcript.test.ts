import { expect, it } from 'vitest'
import { callStatus, groupTranscript } from './transcript'

const entry = (id: string, kind: 'info' | 'error' | 'tool', text = id) => ({ id, kind, text })

it('groups each tool call with the observations that follow it', () => {
  const items = groupTranscript([
    entry('intro', 'info'),
    entry('discover', 'tool'),
    entry('ok', 'info'),
    entry('submitPlan', 'tool'),
    entry('bad', 'error'),
    entry('planWeather', 'tool'),
  ])
  expect(items.map((item) => item.kind)).toEqual(['note', 'call', 'call', 'call'])
  const calls = items.filter((item) => item.kind === 'call')
  expect(calls.map(callStatus)).toEqual(['done', 'failed', 'running'])
  expect(calls[0].results.map((result) => result.id)).toEqual(['ok'])
})

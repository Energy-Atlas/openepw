import { describe, expect, it } from 'vitest'
import { toolAction, transcriptItems } from '../src/transcript'
import type { AgentEvent } from '../src/types'

const tool = (seq: number, text: string, name: string, phase: string): AgentEvent =>
  ({ seq, type: 'tool', text, data: { tool: name, phase, by: 'host' } })

describe('transcript tool lines', () => {
  it('joins a tool result to its call so each tool action is one line', () => {
    const items = transcriptItems([
      { seq: 1, type: 'user', text: 'Cambridge 2018', data: {} },
      tool(2, 'weather_geocode', 'weather_geocode', 'call'),
      tool(3, 'Found 10 location candidates', 'weather_geocode', 'result'),
      tool(4, 'weather_plan', 'weather_plan', 'call'),
    ])
    expect(items.map(item => item.kind === 'tool' ? [item.action, item.result] : item.event.text)).toEqual([
      'Cambridge 2018',
      ['Finding the place', 'Found 10 location candidates'],
      ['Planning the weather files', undefined],
    ])
  })

  it('keeps a result without a matching call as its own line and leaves out form events', () => {
    const items = transcriptItems([tool(1, 'Accepted', 'weather_place_set', 'result'),
      { seq: 2, type: 'form', text: 'Where?', data: {} }])
    expect(items).toMatchObject([{ kind: 'tool', action: 'Listing places' }])
  })

  it('names unknown tools in words', () => {
    expect(toolAction('weather_data_describe')).toBe('weather data describe')
  })
})

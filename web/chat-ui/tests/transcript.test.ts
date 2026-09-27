import { describe, expect, it } from 'vitest'
import { transcriptItems } from '../src/transcript'
import type { ChatEvent } from '../src/types'

const tool = (id: number, text: string, name: string, phase: string): ChatEvent =>
  ({ id, type: 'tool', text, data: { tool: name, phase } })

describe('transcript tool lines', () => {
  it('joins a tool result to its call so each tool action is one line', () => {
    const items = transcriptItems([
      { id: 1, type: 'message', text: 'Cambridge 2018', data: { role: 'user' } },
      tool(2, 'Geocoding place', 'geocode', 'call'),
      tool(3, 'Found 10 location candidates', 'geocode', 'result'),
      tool(4, 'Assessing catalog', 'availability', 'call'),
      tool(5, 'Catalog assessment complete', 'availability', 'result'),
      tool(6, 'Preparing weather plan', 'weather_plan', 'call'),
    ])
    expect(items.map(item => item.kind === 'tool' ? [item.action, item.result] : item.event.text)).toEqual([
      'Cambridge 2018',
      ['Geocoding place', 'Found 10 location candidates'],
      ['Assessing catalog', 'Catalog assessment complete'],
      ['Preparing weather plan', undefined],
    ])
  })

  it('keeps a result without a matching call as its own line', () => {
    const items = transcriptItems([tool(1, 'Geography accepted', 'geography', 'result')])
    expect(items).toMatchObject([{ kind: 'tool', action: 'Geography accepted' }])
  })
})

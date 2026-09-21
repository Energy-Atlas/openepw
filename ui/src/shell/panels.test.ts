import { expect, it } from 'vitest'
import { clampPanelSize, nextDrawer } from './panels'

it('bounds persisted panel sizes and keeps one narrow drawer open', () => {
  expect(clampPanelSize('controls', 100)).toBe(280)
  expect(clampPanelSize('controls', 900)).toBe(520)
  expect(clampPanelSize('agent', 400)).toBe(400)
  expect(nextDrawer('controls', 'agent')).toBe('agent')
  expect(nextDrawer('agent', 'agent')).toBeNull()
})

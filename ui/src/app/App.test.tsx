import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useApp } from './store'
import { App } from './App'

vi.mock('../features/map/MapView', () => ({
  MapView: () => <div data-testid="map-surface">3D globe</div>,
}))
vi.mock('../features/workflow/StagePanel', () => ({
  StagePanel: () => <div>Stage content</div>,
}))
vi.mock('../features/agent/AgentPanel', () => ({
  AgentPanel: () => <div>Agent content</div>,
}))
vi.mock('../shell/theme', () => ({
  useTheme: () => ({
    preference: 'system',
    setPreference: vi.fn(),
    appearance: { chrome: {}, data: {} },
  }),
}))

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1200 })
  useApp.setState({
    stage: 'explore',
    discovery: null,
    discoveryVersion: null,
    downloadJobs: [],
    projectJobs: [],
    importedArtifacts: [],
    activeWeatherArtifact: null,
    busy: false,
  })
})

afterEach(cleanup)

it('keeps fixed panel roles, a map-only center and an ordered stage stepper', () => {
  render(<App />)
  expect(screen.getByRole('complementary', { name: 'Stage controls' })).toBeTruthy()
  expect(screen.getByRole('complementary', { name: 'Agent' })).toBeTruthy()
  expect(screen.getByTestId('map-surface')).toBeTruthy()
  expect(screen.queryByRole('tab')).toBeNull()
  expect(screen.getByRole('button', { name: 'Explore' }).getAttribute('aria-current')).toBe('step')
  expect(screen.getByRole('button', { name: 'Download' }).getAttribute('aria-disabled')).toBe(
    'true',
  )
})

it('opens server history in its own drawer', () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'History' }))
  expect(screen.getByRole('dialog', { name: 'Job history' })).toBeTruthy()
})

it('uses mutually exclusive narrow drawers and restores focus on Escape', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 700 })
  render(<App />)
  const controls = screen.getByRole('button', { name: 'Controls' })
  const agent = screen.getByRole('button', { name: 'Agent panel' })
  fireEvent.click(controls)
  expect(
    screen.getByRole('complementary', { name: 'Stage controls' }).getAttribute('data-open'),
  ).toBe('true')
  fireEvent.click(agent)
  expect(
    screen.getByRole('complementary', { name: 'Stage controls' }).getAttribute('data-open'),
  ).toBe('false')
  expect(screen.getByRole('complementary', { name: 'Agent' }).getAttribute('data-open')).toBe(
    'true',
  )
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('complementary', { name: 'Agent' }).getAttribute('data-open')).toBe(
    'false',
  )
  expect(document.activeElement).toBe(agent)
})

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
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
    pendingConfirmation: null,
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
  const trigger = screen.getByRole('button', { name: 'History' })
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: 'Job history' })).toBeTruthy()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close history' }))
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(document.activeElement).toBe(trigger)
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

it('closes only the confirmation dialog when Escape is pressed above a narrow drawer', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 700 })
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Controls' }))
  act(() =>
    useApp.setState({
      pendingConfirmation: { title: 'Update upstream inputs?', description: 'Stale.' },
    }),
  )
  fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' })
  expect(useApp.getState().pendingConfirmation).toBeNull()
  expect(
    screen.getByRole('complementary', { name: 'Stage controls' }).getAttribute('data-open'),
  ).toBe('true')
})

it('offers a narrow stage selector that reaches earlier stages and respects locks', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 700 })
  useApp.setState({ stage: 'download', discovery: { candidates: [] } as any })
  render(<App />)
  const selector = screen.getByRole('combobox', { name: 'Workflow stage' }) as HTMLSelectElement
  expect(selector.value).toBe('download')
  expect((screen.getByRole('option', { name: /Project/ }) as HTMLOptionElement).disabled).toBe(true)
  fireEvent.change(selector, { target: { value: 'explore' } })
  expect(useApp.getState().stage).toBe('explore')
})

it('makes the map inert while a narrow drawer is open', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 700 })
  render(<App />)
  const map = screen.getByLabelText('Weather map workspace')
  expect(map.hasAttribute('inert')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Controls' }))
  expect(map.hasAttribute('inert')).toBe(true)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(map.hasAttribute('inert')).toBe(false)
})

it('supports keyboard resizing with range semantics', () => {
  render(<App />)
  const separator = screen.getByRole('separator', { name: 'Resize stage controls' })
  expect(separator.getAttribute('aria-valuenow')).toBe('340')
  fireEvent.keyDown(separator, { key: 'ArrowRight' })
  expect(
    screen.getByRole('separator', { name: 'Resize stage controls' }).getAttribute('aria-valuenow'),
  ).toBe('350')
})

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useApp } from '../../app/store'
import { StagePanel } from './StagePanel'
import { RunSplitButton } from './RunSplitButton'

const { run } = vi.hoisted(() => ({ run: vi.fn() }))
vi.mock('../../app/actions', async () => {
  const actual = await vi.importActual<typeof import('../../app/actions')>('../../app/actions')
  return { ...actual, run }
})

beforeEach(() => {
  run.mockReset()
  useApp.setState({
    stage: 'explore',
    requestVersion: 1,
    selectionVersion: 0,
    futureVersion: 0,
    discovery: null,
    discoveryVersion: null,
    selectedDatasets: [],
    weatherPlan: null,
    weatherPlanRequestVersion: null,
    weatherPlanSelectionVersion: null,
    futurePlan: null,
    futurePlanVersion: null,
    futurePlanBaselineId: null,
    spatialPreview: null,
    spatialPreviewVersion: null,
    spatialPreviewAttemptVersion: null,
    downloadJobs: [],
    projectJobs: [],
    importedArtifacts: [],
    activeWeatherArtifact: null,
    job: null,
    busy: false,
    error: '',
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('stage controls', () => {
  it('keeps Explore provider-free and exposes sampling offsets', () => {
    render(<StagePanel />)
    expect(screen.getByRole('heading', { name: 'Explore' })).toBeTruthy()
    expect(screen.queryByLabelText(/provider/i)).toBeNull()
    expect(screen.getByLabelText(/Horizontal spacing/)).toBeTruthy()
    expect(screen.getByLabelText(/Horizontal offset/)).toBeTruthy()
    expect(screen.getByLabelText(/Vertical offset/)).toBeTruthy()
  })

  it('shows authoritative count and a visible disabled Run reason', () => {
    useApp.setState({
      spatialPreview: {
        locations: [],
        total_count: 1200,
        returned_count: 500,
        planned_output_count: 1200,
        execution_limit: 1000,
        executable: false,
        truncated: true,
        issues: [],
      },
      spatialPreviewVersion: 1,
    })
    render(<RunSplitButton />)
    const button = screen.getByRole('button', { name: 'Find availability' })
    expect(button.getAttribute('aria-disabled')).toBe('true')
    const reason = screen.getByText(/Reduce the sample count/i)
    expect(reason).toBeTruthy()
    expect(button.getAttribute('aria-describedby')).toBe(reason.id)
  })

  it('moves focus into the split menu and restores it on Escape', () => {
    render(<RunSplitButton />)
    const trigger = screen.getByRole('button', { name: 'More run options' })
    fireEvent.click(trigger)
    expect(document.activeElement).toBe(
      screen.getByRole('menuitem', { name: 'Refresh sample preview' }),
    )
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
    expect(document.activeElement).toBe(trigger)
  })

  it('traps confirmation focus and restores the exact opener', async () => {
    useApp.setState({
      stage: 'download',
      discovery: { candidates: [{ id: 'candidate' }] } as any,
      discoveryVersion: 1,
      selectedDatasets: [{ provider: 'openmeteo', dataset: 'era5' }],
      selectionVersion: 2,
      weatherPlan: { kind: 'weather', plan_hash: 'current', outputs: [{ name: 'epw' }] } as any,
      weatherPlanRequestVersion: 1,
      weatherPlanSelectionVersion: 2,
    })
    render(<RunSplitButton />)
    const opener = screen.getByRole('button', { name: 'Download weather' })
    fireEvent.click(opener)
    expect(screen.getByRole('alertdialog', { name: 'Confirm Download weather' })).toBeTruthy()
    expect(run).not.toHaveBeenCalled()
    const confirm = screen.getByRole('button', { name: 'Confirm job' })
    const keep = screen.getByRole('button', { name: 'Keep reviewing' })
    expect(document.activeElement).toBe(confirm)
    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Tab' })
    expect(document.activeElement).toBe(keep)
    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirm)
    fireEvent.click(keep)
    await waitFor(() => expect(document.activeElement).toBe(opener))
    expect(run).not.toHaveBeenCalled()
  })

  it('groups Download datasets, toggles whole-query selections and refreshes the plan', () => {
    vi.useFakeTimers()
    useApp.setState({
      stage: 'download',
      discoveryVersion: 1,
      discovery: {
        locations: [],
        selected_candidate_ids: ['a'],
        issues: [],
        observed_at: 'now',
        candidates: [
          {
            id: 'a',
            location_id: 'one',
            source: { provider: 'era5', dataset: 'single-levels' },
            product_id: null,
            variables: [],
            available_years: [2024],
            requires_credentials: [],
            missing_fields: [],
            warnings: [],
            selection_reasons: ['Backend ranked'],
          },
          {
            id: 'b',
            location_id: 'two',
            source: { provider: 'era5', dataset: 'single-levels' },
            product_id: null,
            variables: [],
            available_years: [2024],
            requires_credentials: [],
            missing_fields: [],
            warnings: [],
            selection_reasons: [],
          },
        ],
      } as any,
      selectedDatasets: [{ provider: 'era5', dataset: 'single-levels', product_id: null }],
    })
    render(<StagePanel />)
    expect(screen.getAllByText('era5 / single-levels')).toHaveLength(1)
    fireEvent.click(screen.getByRole('checkbox', { name: /era5 \/ single-levels/i }))
    expect(run).toHaveBeenCalledWith({ type: 'selectDatasets', selections: [] })
    vi.advanceTimersByTime(400)
    expect(run).toHaveBeenCalledWith({ type: 'planWeather' })
  })

  it('retries a deferred live plan refresh after another request finishes', () => {
    vi.useFakeTimers()
    useApp.setState({
      stage: 'download',
      busy: true,
      discoveryVersion: 1,
      discovery: {
        candidates: [
          {
            id: 'a',
            source: { provider: 'era5', dataset: 'single-levels' },
            product_id: null,
          },
        ],
      } as any,
      selectedDatasets: [{ provider: 'era5', dataset: 'single-levels' }],
    })
    render(<StagePanel />)
    vi.advanceTimersByTime(400)
    expect(run).not.toHaveBeenCalledWith({ type: 'planWeather' })

    act(() => useApp.setState({ busy: false }))
    vi.advanceTimersByTime(400)

    expect(run).toHaveBeenCalledWith({ type: 'planWeather' })
  })

  it('shows partial Download outcomes and imported EPWs', () => {
    useApp.setState({
      stage: 'download',
      downloadJobs: [
        {
          id: 'job',
          state: 'partially_completed',
          completed: 1,
          failed: 2,
          total: 3,
          bundle: { weather: [{ id: 'made', path: 'made.epw', role: 'weather' }] },
        } as any,
      ],
      importedArtifacts: [{ id: 'upload', path: 'baseline.epw', role: 'baseline' } as any],
    })
    render(<StagePanel />)
    expect(screen.getByText('1 EPW output created · 2 failed')).toBeTruthy()
    expect(screen.getByText('made.epw')).toBeTruthy()
    expect(screen.getByText('baseline.epw')).toBeTruthy()
  })

  it('shows one active Project baseline and implemented methods only', () => {
    useApp.setState({
      stage: 'project',
      activeWeatherArtifact: {
        id: 'baseline',
        path: 'ithaca.epw',
        role: 'weather',
        media_type: 'application/vnd.energyplus.epw',
      } as any,
      importedArtifacts: [
        {
          id: 'baseline',
          path: 'ithaca.epw',
          role: 'weather',
          media_type: 'application/vnd.energyplus.epw',
        } as any,
      ],
    })
    render(<StagePanel />)
    expect(screen.getByText('ithaca.epw')).toBeTruthy()
    expect(screen.getByRole('option', { name: /monthly morphing/i })).toBeTruthy()
    expect(screen.getByRole('option', { name: /coherent hourly/i })).toBeTruthy()
    expect(screen.queryByRole('option', { name: /sampled/i })).toBeNull()
    expect(screen.getByText(/not a forecast/i)).toBeTruthy()
  })
})

it('starts each stage at the top and scrolls a newly started job into view', () => {
  render(<StagePanel />)
  const panel = screen.getByRole('region', { name: 'Explore controls' })
  panel.scrollTop = 240
  act(() => useApp.setState({ stage: 'download', discovery: { candidates: [] } as any }))
  expect(screen.getByRole('region', { name: 'Download controls' }).scrollTop).toBe(0)

  const download = screen.getByRole('region', { name: 'Download controls' })
  download.scrollTop = 180
  act(() =>
    useApp.setState({
      downloadJobs: [
        { id: 'new-job', kind: 'weather', state: 'queued', total: 2, completed: 0, failed: 0 },
      ] as any,
    }),
  )
  expect(download.scrollTop).toBe(0)
  expect(screen.getByRole('region', { name: 'Downloading weather' })).toBeTruthy()
})

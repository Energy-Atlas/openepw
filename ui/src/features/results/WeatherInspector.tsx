import { ChevronDown, Download, GripHorizontal } from 'lucide-react'
import { useState } from 'react'
import { api } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import type { Appearance } from '../../shell/appearances'
import { WeatherCharts } from './WeatherCharts'
import { WeatherTable } from './WeatherTable'

// Continuous EPW variables the visualization endpoint accepts (see openepw.dataset.UNITS).
export const VARIABLES = [
  ['dni', 'Direct normal irradiance'],
  ['ghi', 'Global horizontal irradiance'],
  ['dhi', 'Diffuse horizontal irradiance'],
  ['horizontal_infrared', 'Horizontal infrared radiation'],
  ['dry_bulb', 'Dry-bulb temperature'],
  ['dew_point', 'Dew-point temperature'],
  ['relative_humidity', 'Relative humidity'],
  ['pressure', 'Station pressure'],
  ['wind_speed', 'Wind speed'],
  ['wind_direction', 'Wind direction'],
  ['total_sky_cover', 'Total sky cover'],
  ['opaque_sky_cover', 'Opaque sky cover'],
  ['visibility', 'Visibility'],
  ['precipitable_water', 'Precipitable water'],
  ['liquid_precipitation', 'Liquid precipitation'],
  ['snow_depth', 'Snow depth'],
  ['albedo', 'Albedo'],
] as const

export function WeatherInspector({ appearance }: { appearance: Appearance }) {
  const state = useApp()
  const [view, setView] = useState<'charts' | 'table'>('charts')
  const visualization = state.visualization
  const artifact = state.artifact
  if (!visualization || !artifact) return null
  const available = Object.keys(visualization.series)
  const hasValues = (variable: string) =>
    visualization.series[variable]?.some((value) => value != null) ?? false
  const usable = available.filter(hasValues)
  // An explicit choice is shown even when all missing, so the gap stays visible.
  const heatVariable =
    state.inspector.variable && available.includes(state.inspector.variable)
      ? state.inspector.variable
      : hasValues('dni')
        ? 'dni'
        : (usable.find((variable) => !['dry_bulb', 'liquid_precipitation'].includes(variable)) ??
          usable[0])
  const heatLabel = VARIABLES.find(([value]) => value === heatVariable)?.[1] ?? heatVariable
  const valid = visualization.series[heatVariable]?.filter((value) => value != null).length ?? 0

  function resize(event: React.PointerEvent) {
    const origin = event.clientY
    const initial = state.panelSizes.inspector
    const move = (pointer: PointerEvent) => {
      run({ type: 'setPanelSize', panel: 'inspector', size: initial + origin - pointer.clientY })
    }
    const stop = () => {
      removeEventListener('pointermove', move)
      removeEventListener('pointerup', stop)
    }
    addEventListener('pointermove', move)
    addEventListener('pointerup', stop)
  }

  return (
    <section
      className="weather-inspector"
      aria-label="Weather inspector"
      style={{ height: state.panelSizes.inspector }}
    >
      <div
        className="inspector-resizer"
        role="separator"
        tabIndex={0}
        aria-label="Resize weather inspector"
        aria-orientation="horizontal"
        aria-valuemin={180}
        aria-valuemax={520}
        aria-valuenow={state.panelSizes.inspector}
        onPointerDown={resize}
        onKeyDown={(event) => {
          if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return
          event.preventDefault()
          run({
            type: 'setPanelSize',
            panel: 'inspector',
            size: state.panelSizes.inspector + (event.key === 'ArrowUp' ? 10 : -10),
          })
        }}
      >
        <GripHorizontal aria-hidden="true" />
      </div>
      <header>
        <div>
          <strong>{artifact.path.split('/').pop()}</strong>
          <span>
            {visualization.total_rows.toLocaleString()} rows · {visualization.calendar} calendar ·{' '}
            {visualization.simulation_ready ? 'simulation ready' : 'review required'}
          </span>
        </div>
        <label>
          Hourly variable
          <select
            value={heatVariable}
            onChange={(event) => {
              const variable = event.target.value
              useApp.setState((current) => ({ inspector: { ...current.inspector, variable } }))
              run({
                type: 'selectArtifact',
                artifact,
                variables: [...new Set(['dry_bulb', 'liquid_precipitation', variable])],
              })
            }}
          >
            {VARIABLES.map(([value, label]) => (
              <option
                key={value}
                value={value}
                disabled={value in visualization.series && !hasValues(value)}
              >
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-label={`Download ${artifact.path.split('/').pop()}`}
          title="Download EPW"
          onClick={() => void api.download(artifact)}
        >
          <Download aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Collapse weather inspector"
          onClick={() => run({ type: 'setInspector', open: false, manually: true })}
        >
          <ChevronDown aria-hidden="true" />
        </button>
      </header>
      <div className="inspector-meta">
        <span className="inspector-view" role="group" aria-label="Inspector view">
          <button type="button" aria-pressed={view === 'charts'} onClick={() => setView('charts')}>
            Charts
          </button>
          <button type="button" aria-pressed={view === 'table'} onClick={() => setView('table')}>
            Table
          </button>
        </span>
        <span>Source years: {formatSourceYears(visualization.source_years)}</span>
        {visualization.total_rows === 8784 && <span>Leap day retained</span>}
        {visualization.synthetic_chronology && (
          <span className="meta-flag">
            Synthetic chronology: source years differ from timestamps
          </span>
        )}
        {heatVariable && (
          <span>
            {heatLabel}: {valid.toLocaleString()} of {visualization.total_rows.toLocaleString()}{' '}
            hours valid
          </span>
        )}
        {!hasValues('liquid_precipitation') && <span>Precipitation unavailable</span>}
        {!hasValues('dni') && (
          <span>DNI unavailable{heatVariable ? `; showing ${heatVariable}` : ''}</span>
        )}
        {visualization.warnings?.map((warning) => (
          <span key={warning}>{warning}</span>
        ))}
      </div>
      {view === 'table' ? (
        <WeatherTable artifactId={artifact.id} preview={state.preview} busy={state.busy} />
      ) : heatVariable ? (
        <WeatherCharts
          visualization={visualization}
          heatVariable={heatVariable}
          heatLabel={heatLabel}
          appearance={appearance}
        />
      ) : (
        <p className="empty-inline">No hourly values are available for this artifact.</p>
      )}
    </section>
  )
}

function formatSourceYears(years: (number | null)[]) {
  const known = [...new Set(years.filter((year): year is number => year != null))].sort()
  if (!known.length) return 'unknown'
  if (known.length <= 4) return known.join(', ')
  return `${known[0]}–${known.at(-1)} (${known.length} years)`
}

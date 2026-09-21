import { ChevronDown, GripHorizontal } from 'lucide-react'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import type { Appearance } from '../../shell/appearances'
import { clampPanelSize } from '../../shell/panels'
import { WeatherCharts } from './WeatherCharts'

const VARIABLES = [
  ['dni', 'Direct normal irradiance'],
  ['ghi', 'Global horizontal irradiance'],
  ['dry_bulb', 'Dry-bulb temperature'],
  ['relative_humidity', 'Relative humidity'],
  ['wind_speed', 'Wind speed'],
] as const

export function WeatherInspector({ appearance }: { appearance: Appearance }) {
  const state = useApp()
  const visualization = state.visualization
  const artifact = state.artifact
  if (!visualization || !artifact) return null
  const available = Object.keys(visualization.series)
  const heatVariable = available.includes('dni')
    ? 'dni'
    : available.find((variable) => !['dry_bulb', 'liquid_precipitation'].includes(variable)) ?? available[0]

  function resize(event: React.PointerEvent) {
    const origin = event.clientY
    const initial = state.panelSizes.inspector
    const move = (pointer: PointerEvent) => {
      const size = clampPanelSize('inspector', initial + origin - pointer.clientY)
      useApp.setState((current) => ({ panelSizes: { ...current.panelSizes, inspector: size } }))
    }
    const stop = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', stop) }
    addEventListener('pointermove', move)
    addEventListener('pointerup', stop)
  }

  return <section className="weather-inspector" aria-label="Weather inspector" style={{ height: state.panelSizes.inspector }}>
    <div className="inspector-resizer" role="separator" aria-label="Resize weather inspector" aria-orientation="horizontal" onPointerDown={resize}>
      <GripHorizontal aria-hidden="true" />
    </div>
    <header>
      <div><strong>{artifact.path.split('/').pop()}</strong><span>{visualization.total_rows.toLocaleString()} rows · {visualization.calendar} calendar · {visualization.simulation_ready ? 'simulation ready' : 'review required'}</span></div>
      <label>Hourly variable
        <select value={heatVariable} onChange={(event) => run({ type: 'selectArtifact', artifact, variables: ['dry_bulb', 'liquid_precipitation', event.target.value] })}>
          {VARIABLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <button type="button" aria-label="Collapse weather inspector" onClick={() => run({ type: 'setInspector', open: false, manually: true })}><ChevronDown aria-hidden="true" /></button>
    </header>
    <div className="inspector-meta">
      <span>Source years: {formatSourceYears(visualization.source_years)}</span>
      {visualization.total_rows === 8784 && <span>Leap day retained</span>}
      {!available.includes('liquid_precipitation') && <span>Precipitation unavailable</span>}
      {!available.includes('dni') && <span>DNI unavailable; showing {heatVariable}</span>}
      {visualization.warnings?.map((warning) => <span key={warning}>{warning}</span>)}
    </div>
    <WeatherCharts visualization={visualization} heatVariable={heatVariable} appearance={appearance} />
  </section>
}

function formatSourceYears(years: (number | null)[]) {
  const known = [...new Set(years.filter((year): year is number => year != null))].sort()
  if (!known.length) return 'unknown'
  if (known.length <= 4) return known.join(', ')
  return `${known[0]}–${known.at(-1)} (${known.length} years)`
}

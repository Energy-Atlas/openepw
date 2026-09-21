import type { Schemas } from '../../api/client'

type Visualization = Schemas['WeatherVisualization']

export function calendarDay(timestamp: string, calendar: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(timestamp)
  if (calendar === 'noleap' && match) {
    const month = Number(match[2])
    const day = Number(match[3])
    const monthLengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return monthLengths.slice(0, month - 1).reduce((sum, length) => sum + length, 0) + day
  }
  const date = new Date(`${timestamp.replace(' ', 'T').slice(0, 19)}Z`)
  return Math.floor((date.getTime() - Date.UTC(date.getUTCFullYear(), 0, 1)) / 86_400_000) + 1
}

/** Hour of the local standard-time interval start, read from the timestamp text. */
export function localHour(timestamp: string) {
  return Number(timestamp.slice(11, 13))
}

export type HeatmapModel = {
  /** Day-of-year labels for the category x axis. */
  days: number[]
  /** [dayIndex, hour, value, rowIndex] for finite values. */
  cells: [number, number, number, number][]
  /** [dayIndex, hour, rowIndex] for missing values, drawn with the no-data token. */
  missing: [number, number, number][]
  min: number
  max: number
}

// Category axes treat numeric data as category indexes, so days are offset from the
// first rendered day rather than passed as day-of-year numbers.
export function heatmapModel(visualization: Visualization, variable: string): HeatmapModel {
  const values = visualization.series[variable] ?? []
  const dayOfYear = visualization.timestamps.map((timestamp) =>
    calendarDay(timestamp, visualization.calendar),
  )
  const firstDay = dayOfYear.length ? Math.min(...dayOfYear) : 1
  const lastDay = dayOfYear.length ? Math.max(...dayOfYear) : 1
  const cells: HeatmapModel['cells'] = []
  const missing: HeatmapModel['missing'] = []
  let min = Infinity
  let max = -Infinity
  visualization.timestamps.forEach((timestamp, index) => {
    const x = dayOfYear[index] - firstDay
    const hour = localHour(timestamp)
    const value = values[index]
    if (value == null || !Number.isFinite(value)) {
      missing.push([x, hour, index])
      return
    }
    cells.push([x, hour, value, index])
    min = Math.min(min, value)
    max = Math.max(max, value)
  })
  if (!cells.length) {
    min = 0
    max = 1
  } else if (min === max) {
    // A constant series still needs a non-empty range for the color scale.
    const pad = Math.max(Math.abs(min) * 0.01, 1)
    min -= pad
    max += pad
  }
  return {
    days: Array.from({ length: lastDay - firstDay + 1 }, (_, index) => firstDay + index),
    cells,
    missing,
    min,
    max,
  }
}

/** Month label for a server (year, month) pair, independent of the viewer's time zone. */
export function monthLabel(year: number, month: number) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  )
}

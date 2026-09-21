import { expect, it } from 'vitest'
import { calendarDay, heatmapModel, localHour, monthLabel } from './heatmap'
import { heatmapOptions } from './WeatherCharts'
import { APPEARANCES } from '../../shell/appearances'

it('maps leap chronology according to the artifact calendar', () => {
  expect(calendarDay('2024-02-28T12:00:00', 'noleap')).toBe(59)
  expect(calendarDay('2024-03-01T12:00:00', 'noleap')).toBe(60)
  expect(calendarDay('2024-03-01T12:00:00', 'gregorian')).toBe(61)
})

const visualization = (series: (number | null)[], timestamps: string[]) =>
  ({
    calendar: 'gregorian',
    timestamps,
    series: { dni: series },
  }) as any

it('indexes heatmap days from the first rendered day so the last day is kept', () => {
  const model = heatmapModel(
    visualization(
      [1, 5, null],
      ['2024-01-01T00:00:00', '2024-01-01T13:00:00', '2024-12-31T23:00:00'],
    ),
    'dni',
  )
  expect(model.days[0]).toBe(1)
  expect(model.days.at(-1)).toBe(366)
  expect(model.cells).toEqual([
    [0, 0, 1, 0],
    [0, 13, 5, 1],
  ])
  // Missing values are kept as their own cells, including on the final day.
  expect(model.missing).toEqual([[365, 23, 2]])
})

it('scales colors to the observed range rather than forcing zero or one', () => {
  const pressure = heatmapModel(
    visualization([100900, 101700], ['2024-01-01T00:00:00', '2024-01-01T01:00:00']),
    'dni',
  )
  expect([pressure.min, pressure.max]).toEqual([100900, 101700])
  const negative = heatmapModel(
    visualization([-12.5, -3], ['2024-01-01T00:00:00', '2024-01-01T01:00:00']),
    'dni',
  )
  expect([negative.min, negative.max]).toEqual([-12.5, -3])
})

it('gives a constant series a non-empty color range', () => {
  const model = heatmapModel(
    visualization([0, 0], ['2024-01-01T00:00:00', '2024-01-01T01:00:00']),
    'dni',
  )
  expect(model.min).toBeLessThan(0)
  expect(model.max).toBeGreaterThan(0)
})

it('reads the local interval hour from the timestamp text', () => {
  expect(localHour('2024-07-01T17:00:00')).toBe(17)
})

it('labels months independently of the viewer time zone', () => {
  // Formatting a UTC month start in a western local zone used to yield the prior month.
  expect(monthLabel(2024, 1)).toBe(
    new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(
      new Date(Date.UTC(2024, 0, 15)),
    ),
  )
})

it('colors heatmap cells by value on the sequential palette with a no-data map', () => {
  const options = heatmapOptions(
    {
      ...visualization(
        [100, null, 300],
        ['2024-01-01T00:00:00', '2024-01-01T01:00:00', '2024-01-02T00:00:00'],
      ),
      units: { dni: 'Wh/m2' },
      source_years: [2024, 2024, 2024],
    },
    'dni',
    'Direct normal irradiance',
    APPEARANCES.light,
  ) as any
  const [values, missing] = options.visualMap
  // Cells are [day, hour, value, row]; ECharts would otherwise color by the last (row) dimension.
  expect(values).toMatchObject({
    seriesIndex: 0,
    dimension: 2,
    min: 100,
    max: 300,
  })
  expect(values.inRange.color).toEqual([...APPEARANCES.light.data.sequential])
  expect(missing).toMatchObject({ seriesIndex: 1, show: false })
  expect(missing.inRange.color).toEqual([
    APPEARANCES.light.data.noData,
    APPEARANCES.light.data.noData,
  ])
  expect(options.series[1].data).toEqual([[0, 1, 1]])
})

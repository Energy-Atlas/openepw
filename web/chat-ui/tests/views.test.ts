import { describe, expect, it } from 'vitest'
import { chartOption } from '../src/views/options'
import type { ViewSpec } from '../src/types'
import { SERIES, THEME } from '../src/theme'

const base: ViewSpec = {
  schema_version: '1', family: 'monthly_series',
  data_ref: { view_id: 'x', shape: 'rows', total_rows: 2 },
  encodings: { y: { unit: 'Wh/m2' } }, sources: [],
  quality: { expected_hours: 744, valid_hours: 700, missing_hours: 44 }, summary: 'partial',
}

describe('prepared-data chart options', () => {
  it('keeps missing monthly values null and the published unit', () => {
    const option = chartOption(base, [
      { artifact_id: 'first', period: '2018-01', value: 8 },
      { artifact_id: 'first', period: '2018-02', value: null },
    ])!
    expect((option.yAxis as { name: string }).name).toBe('Wh/m2')
    expect((option.series as Array<{ data: unknown[] }>)[0].data).toEqual([8, null])
  })

  it('uses a matrix only when the prepared spec declares one', () => {
    const option = chartOption({ ...base, family: 'spatial', data_ref: { ...base.data_ref, shape: 'matrix' },
      encodings: { latitudes: [1], longitudes: [2, 3], values: [[4, null]], value: { unit: '°C' } } }, [])!
    expect((option.series as Array<{ type: string }>)[0].type).toBe('heatmap')
    expect(chartOption({ ...base, schema_version: '2' }, [])).toBeNull()
  })

  it('keeps an all-missing spatial range finite', () => {
    const option = chartOption({ ...base, family: 'spatial', data_ref: { ...base.data_ref, shape: 'matrix' },
      encodings: { latitudes: [1], longitudes: [2], values: [[null]], value: { unit: '°C' } } }, [])!
    expect(option.visualMap).toMatchObject({ min: 0, max: 1 })
  })

  it('labels histogram bins with the weather variable unit', () => {
    const option = chartOption({ ...base, family: 'histogram', encodings: {
      x: { unit: 'degC' }, y: { unit: 'hours' },
    } }, [{ artifact_id: 'one', bin_start: 0, bin_end: 5, count: 10 }])!
    expect((option.xAxis as { name: string }).name).toBe('degC')
    expect((option.yAxis as { name: string }).name).toBe('hours')
  })

  it('draws every chart family in the OpenEPW theme', () => {
    const series = chartOption(base, [{ artifact_id: 'a', period: '2018-01', value: 1 }])!
    expect(series.color).toEqual([...SERIES])
    expect(series.textStyle).toMatchObject({ color: THEME.INK })
    const matrix = chartOption({ ...base, family: 'spatial', data_ref: { ...base.data_ref, shape: 'matrix' },
      encodings: { latitudes: [1], longitudes: [2], values: [[4]], value: { unit: '°C' } } }, [])!
    expect(matrix.visualMap).toMatchObject({ inRange: { color: [...THEME.RAMP] } })
    const points = chartOption({ ...base, family: 'spatial', data_ref: { ...base.data_ref, shape: 'points' } },
      [{ lon: 1, lat: 2, value: 3 }, { lon: 2, lat: 3, value: 5 }])!
    expect(points.visualMap).toMatchObject({ min: 3, max: 5, inRange: { color: [...THEME.RAMP] } })
  })
})

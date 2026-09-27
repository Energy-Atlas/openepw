import { describe, expect, it } from 'vitest'
import { chartOption } from '../src/views/options'
import type { ViewSpec } from '../src/types'

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
})

import type { ViewSpec } from '../types'

type Row = Record<string, unknown>

export function chartOption(spec: ViewSpec, rows: Row[]): Record<string, unknown> | null {
  if (spec.schema_version !== '1') return null
  const family = spec.family
  const unit = String((spec.encodings.y as Record<string, unknown> | undefined)?.unit ??
    (spec.encodings.value as Record<string, unknown> | undefined)?.unit ?? '')
  if (['time_series', 'annual_series', 'monthly_series'].includes(family)) {
    const periods = [...new Set(rows.map(row => String(row.period)))]
    const ids = [...new Set(rows.map(row => String(row.artifact_id)))]
    return { tooltip: { trigger: 'axis' }, legend: { type: 'scroll', bottom: 0 },
      grid: { left: 62, right: 18, top: 35, bottom: 64 },
      xAxis: { type: 'category', data: periods, axisLabel: { hideOverlap: true } },
      yAxis: { type: 'value', name: unit }, dataZoom: family === 'time_series' ? [{ type: 'inside' }, { type: 'slider', bottom: 28 }] : undefined,
      series: ids.map(id => {
        const values = new Map(rows.filter(row => row.artifact_id === id).map(row => [String(row.period), row.value]))
        return { name: id.slice(0, 8), type: family === 'monthly_series' ? 'bar' : 'line',
          connectNulls: false, showSymbol: family !== 'time_series',
          data: periods.map(period => values.get(period) ?? null) }
      }) }
  }
  if (family === 'histogram') {
    const binUnit = String((spec.encodings.x as Record<string, unknown> | undefined)?.unit ?? '')
    const ids = [...new Set(rows.map(row => String(row.artifact_id)))]
    const bins = [...new Set(rows.map(row => `${row.bin_start}–${row.bin_end}`))]
    return { tooltip: { trigger: 'axis' }, legend: { bottom: 0 },
      grid: { left: 48, right: 12, top: 20, bottom: 72 },
      xAxis: { type: 'category', name: binUnit, data: bins, axisLabel: { rotate: 35 } },
      yAxis: { type: 'value', name: 'hours' },
      series: ids.map(id => ({ name: id.slice(0, 8), type: 'bar', data: rows.filter(row => row.artifact_id === id).map(row => row.count) })) }
  }
  if (family === 'spatial') {
    if (spec.data_ref.shape === 'matrix') {
      const latitudes = spec.encodings.latitudes as number[]
      const longitudes = spec.encodings.longitudes as number[]
      const values = spec.encodings.values as Array<Array<number | null>>
      const valid = values.flat().filter((value): value is number => value !== null && Number.isFinite(value))
      return { tooltip: { trigger: 'item' }, grid: { left: 55, right: 30, top: 22, bottom: 48 },
        xAxis: { type: 'category', name: 'longitude', data: longitudes },
        yAxis: { type: 'category', name: 'latitude', data: latitudes },
        visualMap: { min: valid.length ? Math.min(...valid) : 0,
          max: valid.length ? Math.max(...valid) : 1,
          calculable: true, orient: 'horizontal', bottom: 0 },
        series: [{ type: 'heatmap', data: values.flatMap((line, y) => line.map((value, x) => [x, y, value])) }] }
    }
    if (spec.data_ref.shape === 'points') {
      return { tooltip: { trigger: 'item' }, grid: { left: 55, right: 18, top: 25, bottom: 45 },
        xAxis: { type: 'value', name: 'longitude' }, yAxis: { type: 'value', name: 'latitude' },
        series: [{ type: 'scatter', symbolSize: 13,
          data: rows.map(row => [row.lon, row.lat, row.value]) }] }
    }
  }
  return null
}

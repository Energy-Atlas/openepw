import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import type { Schemas } from '../../api/client'
import type { Appearance } from '../../shell/appearances'
export function WeatherCharts({
  preview,
  appearance,
}: {
  preview: Schemas['WeatherPreview']
  appearance: Appearance
}) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current) return
    const chart = echarts.init(host.current)
    chart.setOption({
      textStyle: { fontFamily: 'Geist Variable', color: appearance.chrome.textMuted },
      tooltip: { trigger: 'axis' },
      legend: { data: ['Temperature', 'GHI'], textStyle: { color: appearance.chrome.text } },
      grid: { left: 50, right: 55, top: 45, bottom: 65 },
      xAxis: {
        type: 'category',
        data: preview.rows.map(
          (r) => r.timestamp + (r.source_year == null ? '' : ` (source ${r.source_year})`),
        ),
        axisLabel: { formatter: (v: string) => v.slice(5, 16).replace('T', ' ') },
        axisLine: { lineStyle: { color: appearance.chrome.border } },
      },
      yAxis: [
        {
          type: 'value',
          name: '°C',
          splitLine: { lineStyle: { color: appearance.chrome.borderSubtle } },
        },
        { type: 'value', name: 'Wh/m²', splitLine: { show: false } },
      ],
      series: [
        {
          name: 'Temperature',
          type: 'line',
          symbol: 'none',
          connectNulls: false,
          data: preview.rows.map((r) => r.values.dry_bulb),
          lineStyle: { color: appearance.data.categorical[0] },
        },
        {
          name: 'GHI',
          type: 'line',
          symbol: 'none',
          yAxisIndex: 1,
          connectNulls: false,
          data: preview.rows.map((r) => r.values.ghi),
          lineStyle: { color: appearance.data.categorical[1] },
        },
      ],
    })
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(host.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [preview, appearance])
  return (
    <div
      ref={host}
      className="weather-chart"
      role="img"
      aria-label="Hourly temperature and solar energy chart; missing values are gaps"
    />
  )
}

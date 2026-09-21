import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import type { Schemas } from '../../api/client'
import type { Appearance } from '../../shell/appearances'
import { heatmapModel, monthLabel } from './heatmap'

export { calendarDay } from './heatmap'

function formatValue(value: number) {
  const magnitude = Math.abs(value)
  return magnitude >= 1000
    ? value.toFixed(0)
    : magnitude >= 10
      ? value.toFixed(1)
      : value.toFixed(2)
}

export function heatmapOptions(
  visualization: Schemas['WeatherVisualization'],
  heatVariable: string,
  heatLabel: string | undefined,
  appearance: Appearance,
  reducedMotion = false,
) {
  const heatUnit = visualization.units[heatVariable] ?? ''
  const model = heatmapModel(visualization, heatVariable)
  const tooltipRow = (index: number, value: string) => {
    const year = visualization.source_years[index]
    return `${visualization.timestamps[index]}<br/>${value}<br/>Source year: ${year ?? 'unknown'}`
  }
  return {
    animation: !reducedMotion,
    textStyle: { fontFamily: 'Geist Variable', color: appearance.chrome.textMuted },
    grid: { left: 36, right: 16, top: 34, bottom: 22 },
    tooltip: {
      formatter: (params: { seriesIndex: number; value: number[] }) =>
        params.seriesIndex === 0
          ? tooltipRow(params.value[3], `${formatValue(params.value[2])} ${heatUnit}`)
          : tooltipRow(params.value[2], 'Missing value'),
    },
    xAxis: {
      type: 'category',
      data: model.days,
      axisLabel: { fontSize: 10 },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'category',
      data: Array.from({ length: 24 }, (_, hour) => hour),
      axisLabel: { fontSize: 10, interval: 5 },
      axisTick: { show: false },
    },
    // ECharts needs a visual map per heatmap series; missing cells get a flat no-data color.
    visualMap: [
      {
        type: 'continuous',
        seriesIndex: 0,
        // Cells are [day, hour, value, row]; without this ECharts colors by the row index.
        dimension: 2,
        min: model.min,
        max: model.max,
        calculable: false,
        orient: 'horizontal',
        top: 0,
        right: 16,
        itemWidth: 10,
        itemHeight: 120,
        precision: Math.abs(model.max - model.min) >= 10 ? 0 : 1,
        text: [`${formatValue(model.max)} ${heatUnit}`, formatValue(model.min)],
        textGap: 6,
        textStyle: { color: appearance.chrome.textMuted, fontSize: 10 },
        inRange: { color: [...appearance.data.sequential] },
      },
      {
        type: 'continuous',
        seriesIndex: 1,
        show: false,
        dimension: 2,
        min: 0,
        max: Math.max(visualization.timestamps.length, 1),
        inRange: { color: [appearance.data.noData, appearance.data.noData] },
      },
    ],
    series: [
      {
        name: heatLabel ?? heatVariable,
        type: 'heatmap',
        data: model.cells,
        progressive: 2000,
        emphasis: { itemStyle: { borderColor: appearance.chrome.text, borderWidth: 1 } },
      },
      {
        name: 'Missing',
        type: 'heatmap',
        data: model.missing,
        itemStyle: { color: appearance.data.noData },
        progressive: 2000,
      },
    ],
  }
}

export function WeatherCharts({
  visualization,
  heatVariable,
  heatLabel,
  appearance,
}: {
  visualization: Schemas['WeatherVisualization']
  heatVariable: string
  heatLabel?: string
  appearance: Appearance
}) {
  const monthlyHost = useRef<HTMLDivElement>(null)
  const heatHost = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!monthlyHost.current) return
    const chart = echarts.init(monthlyHost.current)
    const months = visualization.monthly.map((summary) => monthLabel(summary.year, summary.month))
    const count = (index: number, variable: string) => {
      const summary = visualization.monthly[index]
      return `${summary.values[variable]?.valid ?? 0}/${summary.expected} valid`
    }
    chart.setOption({
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      textStyle: { fontFamily: 'Geist Variable', color: appearance.chrome.textMuted },
      tooltip: {
        trigger: 'axis',
        formatter: (params: { dataIndex: number; seriesName: string; value: number | null }[]) => {
          const index = params[0]?.dataIndex ?? 0
          const lines = params.map((param) => {
            const variable =
              param.seriesName === 'Temperature' ? 'dry_bulb' : 'liquid_precipitation'
            const unit = visualization.units[variable] ?? ''
            const value = param.value == null ? 'missing' : `${formatValue(param.value)} ${unit}`
            return `${param.seriesName}: ${value} (${count(index, variable)})`
          })
          return [months[index], ...lines].join('<br/>')
        },
      },
      legend: {
        top: 0,
        right: 8,
        itemWidth: 14,
        itemHeight: 8,
        data: ['Temperature', 'Precipitation'],
        textStyle: { color: appearance.chrome.text, fontSize: 11 },
      },
      grid: { left: 44, right: 48, top: 44, bottom: 24 },
      xAxis: {
        type: 'category',
        data: months,
        axisLabel: { fontSize: 10, hideOverlap: true },
        axisLine: { lineStyle: { color: appearance.chrome.border } },
      },
      yAxis: [
        {
          type: 'value',
          name: visualization.units.dry_bulb ?? '°C',
          nameTextStyle: { align: 'right' },
          splitLine: { lineStyle: { color: appearance.chrome.borderSubtle } },
        },
        {
          type: 'value',
          name: visualization.units.liquid_precipitation ?? 'mm',
          nameTextStyle: { align: 'left' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Temperature',
          type: 'line',
          connectNulls: false,
          z: 3,
          data: visualization.monthly.map((item) => item.values.dry_bulb?.mean ?? null),
          lineStyle: { color: appearance.data.categorical[0] },
          itemStyle: { color: appearance.data.categorical[0] },
        },
        {
          name: 'Precipitation',
          type: 'bar',
          yAxisIndex: 1,
          barMaxWidth: 14,
          data: visualization.monthly.map((item) => item.values.liquid_precipitation?.sum ?? null),
          itemStyle: { color: appearance.data.categorical[1] },
        },
      ],
    })
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(monthlyHost.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [visualization, appearance])

  useEffect(() => {
    if (!heatHost.current) return
    const chart = echarts.init(heatHost.current)
    chart.setOption(
      heatmapOptions(
        visualization,
        heatVariable,
        heatLabel,
        appearance,
        matchMedia('(prefers-reduced-motion: reduce)').matches,
      ),
    )
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(heatHost.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [visualization, heatVariable, heatLabel, appearance])

  return (
    <div className="weather-charts">
      <div
        ref={monthlyHost}
        className="monthly-chart"
        role="img"
        aria-label="Monthly mean temperature and precipitation totals with valid-sample counts; missing values appear as gaps"
      />
      <div
        ref={heatHost}
        className="heatmap-chart"
        role="img"
        aria-label={`Hourly ${heatVariable} heatmap by day of year and hour on a sequential color scale; missing values use the no-data color`}
      />
    </div>
  )
}

import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import type { Schemas } from '../../api/client'
import type { Appearance } from '../../shell/appearances'

export function calendarDay(timestamp: string, calendar: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(timestamp)
  if (calendar === 'noleap' && match) {
    const month = Number(match[2])
    const day = Number(match[3])
    const monthLengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return monthLengths.slice(0, month - 1).reduce((sum, length) => sum + length, 0) + day
  }
  const date = new Date(`${timestamp.replace(' ', 'T')}Z`)
  return Math.floor((date.getTime() - Date.UTC(date.getUTCFullYear(), 0, 1)) / 86_400_000) + 1
}

export function WeatherCharts({
  visualization,
  heatVariable,
  appearance,
}: {
  visualization: Schemas['WeatherVisualization']
  heatVariable: string
  appearance: Appearance
}) {
  const monthlyHost = useRef<HTMLDivElement>(null)
  const heatHost = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!monthlyHost.current) return
    const chart = echarts.init(monthlyHost.current)
    const months = visualization.monthly.map((summary) =>
      new Intl.DateTimeFormat(undefined, { month: 'short' }).format(
        new Date(Date.UTC(summary.year, summary.month - 1, 1)),
      ),
    )
    chart.setOption({
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      textStyle: { fontFamily: 'Geist Variable', color: appearance.chrome.textMuted },
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['Temperature', 'Precipitation'],
        textStyle: { color: appearance.chrome.text },
      },
      grid: { left: 48, right: 54, top: 38, bottom: 30 },
      xAxis: {
        type: 'category',
        data: months,
        axisLine: { lineStyle: { color: appearance.chrome.border } },
      },
      yAxis: [
        {
          type: 'value',
          name: visualization.units.dry_bulb ?? '°C',
          splitLine: { lineStyle: { color: appearance.chrome.borderSubtle } },
        },
        {
          type: 'value',
          name: visualization.units.liquid_precipitation ?? 'mm',
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Temperature',
          type: 'line',
          connectNulls: false,
          data: visualization.monthly.map((item) => item.values.dry_bulb?.mean ?? null),
          lineStyle: { color: appearance.data.categorical[0] },
          itemStyle: { color: appearance.data.categorical[0] },
        },
        {
          name: 'Precipitation',
          type: 'bar',
          yAxisIndex: 1,
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
    const values = visualization.series[heatVariable] ?? []
    const renderedDays = visualization.timestamps.map((timestamp) =>
      calendarDay(timestamp, visualization.calendar),
    )
    const firstDay = renderedDays.length ? Math.min(...renderedDays) : 1
    const lastDay = renderedDays.length ? Math.max(...renderedDays) : 1
    const data = values.flatMap((value, index) =>
      value == null
        ? []
        : [
            [
              calendarDay(visualization.timestamps[index], visualization.calendar),
              new Date(`${visualization.timestamps[index].replace(' ', 'T')}Z`).getUTCHours(),
              value,
              index,
            ],
          ],
    )
    chart.setOption({
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      textStyle: { fontFamily: 'Geist Variable', color: appearance.chrome.textMuted },
      grid: { left: 42, right: 20, top: 12, bottom: 32 },
      tooltip: {
        formatter: (params: { value: [number, number, number, number] }) => {
          const index = params.value[3]
          const year = visualization.source_years[index]
          return `${visualization.timestamps[index]}<br/>${params.value[2]} ${visualization.units[heatVariable] ?? ''}<br/>Source year: ${year ?? 'unknown'}`
        },
      },
      xAxis: {
        type: 'category',
        name: 'day',
        data: Array.from({ length: lastDay - firstDay + 1 }, (_, index) => firstDay + index),
        splitLine: { show: false },
      },
      yAxis: {
        type: 'category',
        name: 'hour',
        data: Array.from({ length: 24 }, (_, hour) => hour),
        splitLine: { lineStyle: { color: appearance.chrome.borderSubtle } },
      },
      visualMap: {
        show: false,
        min: Math.min(...data.map((item) => Number(item[2])), 0),
        max: Math.max(...data.map((item) => Number(item[2])), 1),
        inRange: {
          color: [
            appearance.chrome.surfaceRaised,
            appearance.data.categorical[1],
            appearance.data.categorical[2],
          ],
        },
      },
      series: [
        {
          type: 'heatmap',
          data,
          progressive: 2000,
          emphasis: { itemStyle: { borderColor: appearance.chrome.text, borderWidth: 1 } },
        },
      ],
    })
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(heatHost.current)
    return () => {
      resize.disconnect()
      chart.dispose()
    }
  }, [visualization, heatVariable, appearance])

  return (
    <div className="weather-charts">
      <div
        ref={monthlyHost}
        className="monthly-chart"
        role="img"
        aria-label="Monthly mean temperature and precipitation totals; missing values appear as gaps"
      />
      <div
        ref={heatHost}
        className="heatmap-chart"
        role="img"
        aria-label={`Hourly ${heatVariable} heatmap by day of year and hour; missing values are blank`}
      />
    </div>
  )
}

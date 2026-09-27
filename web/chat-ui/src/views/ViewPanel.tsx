import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { ChatApi } from '../api'
import type { ViewPage, ViewSpec } from '../types'
import { chartOption } from './options'

function Chart({ spec, rows }: { spec: ViewSpec; rows: ViewPage['rows'] }) {
  const host = useRef<HTMLDivElement>(null)
  const option = chartOption(spec, rows)
  useEffect(() => {
    if (!host.current || !option) return
    let live = true
    let chart: import('echarts').ECharts | undefined
    let observer: ResizeObserver | undefined
    void import('echarts').then(echarts => {
      if (!live || !host.current) return
      chart = echarts.init(host.current)
      chart.setOption(option)
      observer = new ResizeObserver(() => chart?.resize())
      observer.observe(host.current)
    })
    return () => { live = false; observer?.disconnect(); chart?.dispose() }
  }, [spec, rows, option && JSON.stringify(option)])
  return option ? <div ref={host} className="view-chart" role="img" aria-label={`${spec.family} chart; data table follows`} />
    : <p>Unsupported chart version or family. Prepared data remains available below.</p>
}

export function ViewPanel({ id, api, index, onClose }: {
  id: string; api: ChatApi; index: number; onClose: () => void
}) {
  const [page, setPage] = useState<ViewPage | null>(null)
  const [rows, setRows] = useState<ViewPage['rows']>([])
  const [error, setError] = useState('')
  const [minimized, setMinimized] = useState(false)
  const [table, setTable] = useState(false)
  const [position, setPosition] = useState({ x: window.innerWidth <= 650 ? 10 : 28 + index * 18,
    y: window.innerWidth <= 650 ? 38 + index * 18 : 95 + index * 25 })
  const [size, setSize] = useState({
    width: window.innerWidth <= 650 ? Math.max(300, window.innerWidth - 24)
      : Math.max(300, Math.min(480, window.innerWidth - 445 - index * 18)),
    height: window.innerWidth <= 650 ? Math.max(220, Math.min(340, window.innerHeight * .5 - 30)) : 370,
  })
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)

  useEffect(() => {
    let live = true
    void api.pageView(id).then(result => {
      if (live) { setPage(result); setRows(result.rows) }
    }).catch(() => { if (live) setError('Prepared view could not be loaded.') })
    return () => { live = false }
  }, [id, api])

  function pointerDown(event: PointerEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest('button')) return
    drag.current = { x: event.clientX, y: event.clientY, left: position.x, top: position.y }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  function pointerMove(event: PointerEvent<HTMLElement>) {
    if (!drag.current) return
    const maxX = window.innerWidth <= 650 ? window.innerWidth - size.width
      : window.innerWidth - 410 - size.width
    const maxY = window.innerWidth <= 650 ? window.innerHeight * .54 - size.height
      : window.innerHeight - size.height
    setPosition({ x: Math.max(0, Math.min(maxX, drag.current.left + event.clientX - drag.current.x)),
      y: Math.max(0, Math.min(maxY, drag.current.top + event.clientY - drag.current.y)) })
  }
  function keyMove(event: KeyboardEvent<HTMLElement>) {
    const delta = { ArrowLeft: [-12, 0], ArrowRight: [12, 0], ArrowUp: [0, -12], ArrowDown: [0, 12] }[event.key]
    if (!delta) return
    event.preventDefault()
    if (event.altKey) setSize(current => ({ width: Math.max(300, current.width + delta[0]),
      height: Math.max(220, current.height + delta[1]) }))
    else setPosition(current => ({ x: Math.max(0, current.x + delta[0]), y: Math.max(0, current.y + delta[1]) }))
  }

  const spec = page?.specs?.[0]
  return <section className="view-panel" aria-label={`Weather view ${index + 1}`}
    style={{ left: position.x, top: position.y, width: size.width, height: minimized ? 'auto' : size.height }}>
    <header className="view-handle" tabIndex={0} aria-label="Move view with arrow keys; Alt and arrows resize"
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={() => { drag.current = null }}
      onKeyDown={keyMove}>
      <strong>{spec?.family.replaceAll('_', ' ') ?? 'Loading weather view'}</strong>
      <div><button type="button" onClick={() => setMinimized(value => !value)}>{minimized ? 'Restore' : 'Minimize'}</button>
        <button type="button" onClick={onClose} aria-label="Close view">×</button></div>
    </header>
    {!minimized && <div className="view-content">
      {error && <p role="alert">{error}</p>}
      {spec && <>
        <p className="view-summary">{spec.summary} {String((spec.encodings.y as Record<string, unknown> | undefined)?.unit ??
          (spec.encodings.value as Record<string, unknown> | undefined)?.unit ?? '')}</p>
        <p className="view-quality">{spec.quality.valid_hours}/{spec.quality.expected_hours} valid hours · {spec.quality.missing_hours} missing</p>
        {spec.sources.map((source, i) => <p className="view-source" key={i}>
          {String(source.provider ?? 'User EPW')} {source.dataset ? `· ${String(source.dataset)}` : ''}
          {' · '}{Array.isArray(source.years) && source.years.length ? (source.years as number[]).join(', ') : 'reference or unverified period'}
          {' · '}{String(source.calendar ?? 'calendar unknown')} · {String(source.artifact_id ?? '').slice(0, 10)}
        </p>)}
        <Chart spec={spec} rows={rows} />
        <button type="button" onClick={() => setTable(value => !value)}>{table ? 'Hide' : 'Show'} data table</button>
        {table && <div className="view-table" role="region" aria-label="Prepared data rows" tabIndex={0}>
          <table><thead><tr>{Object.keys(rows[0] ?? {}).map(key => <th key={key}>{key}</th>)}</tr></thead>
            <tbody>{rows.slice(0, 30).map((row, i) => <tr key={i}>{Object.values(row).map((value, j) =>
              <td key={j}>{value === null ? 'missing' : String(value)}</td>)}</tr>)}</tbody></table>
        </div>}
        {page?.next_offset !== null && <button type="button" onClick={() => {
          void api.pageView(id, page!.next_offset!).then(next => {
            setRows(current => [...current, ...next.rows]); setPage({ ...page!, next_offset: next.next_offset })
          }).catch(() => setError('Next data page could not be loaded.'))
        }}>Load more ({rows.length}/{page?.total_rows})</button>}
        <details><summary>Source and JSON spec</summary><pre>{JSON.stringify(spec, null, 2)}</pre></details>
      </>}
    </div>}
  </section>
}

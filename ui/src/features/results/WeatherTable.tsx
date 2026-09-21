import { useEffect } from 'react'
import type { Schemas } from '../../api/client'
import { run } from '../../app/actions'

const PAGE = 168

/** Paged hourly rows for the active artifact; missing values are shown, never blank. */
export function WeatherTable({
  artifactId,
  preview,
  busy,
}: {
  artifactId: string
  preview: Schemas['WeatherPreview'] | null
  busy: boolean
}) {
  useEffect(() => {
    if (!preview && !busy) run({ type: 'previewPage', start: 0 })
  }, [artifactId, preview, busy])

  if (!preview) return <p className="empty-inline">Loading hourly rows…</p>
  const variables = Object.keys(preview.units)
  const first = preview.start + 1
  const last = preview.start + preview.rows.length
  return (
    <div className="weather-table">
      <div className="weather-table-pager">
        <button
          type="button"
          disabled={busy || preview.start === 0}
          onClick={() => run({ type: 'previewPage', start: Math.max(0, preview.start - PAGE) })}
        >
          Previous week
        </button>
        <span role="status">
          Rows {first.toLocaleString()}–{last.toLocaleString()} of{' '}
          {preview.total_rows.toLocaleString()}
        </span>
        <button
          type="button"
          disabled={busy || last >= preview.total_rows}
          onClick={() => run({ type: 'previewPage', start: preview.start + PAGE })}
        >
          Next week
        </button>
      </div>
      <div className="weather-table-scroll">
        <table>
          <caption className="sr-only">Hourly weather values; missing values are marked</caption>
          <thead>
            <tr>
              <th scope="col">Local interval start</th>
              <th scope="col">Source year</th>
              {variables.map((variable) => (
                <th scope="col" key={variable}>
                  {variable} <small>{preview.units[variable]}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row) => (
              <tr key={row.timestamp}>
                <th scope="row">{row.timestamp.replace('T', ' ').slice(0, 16)}</th>
                <td>{row.source_year ?? 'unknown'}</td>
                {variables.map((variable) => {
                  const value = row.values[variable]
                  return value == null ? (
                    <td key={variable} className="no-data">
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">missing</span>
                    </td>
                  ) : (
                    <td key={variable}>{Number(value).toFixed(1)}</td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

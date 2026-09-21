import { useState } from 'react'
import type { Artifact } from '../../api/client'
import { run } from '../../app/actions'

export type DatasetPointStatus = {
  label: string
  state: 'available' | 'selected' | 'complete' | 'failed' | 'gated' | 'unavailable'
  color: string
}

export function PointGlyph({
  label,
  statuses,
  artifacts,
}: {
  label: string
  statuses: DatasetPointStatus[]
  artifacts: Artifact[]
}) {
  const [open, setOpen] = useState(false)
  const segments = statuses.length || 1
  const gradient = statuses.length
    ? `conic-gradient(${statuses
        .flatMap((status, index) => segmentStops(status, index, segments))
        .join(',')})`
    : 'var(--color-muted)'
  const description = statuses.length
    ? statuses.map((status) => `${status.label}: ${status.state}`).join(', ')
    : 'No dataset status yet'
  return (
    <div className="point-glyph-wrap">
      <button
        type="button"
        className="point-glyph"
        style={{ background: gradient }}
        aria-label={`${label}. ${description}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span />
      </button>
      {open && (
        <section className="point-popover" aria-label={`${label} details`}>
          <header>
            <strong>{label}</strong>
            <button type="button" aria-label="Close point details" onClick={() => setOpen(false)}>
              ×
            </button>
          </header>
          <ul>
            {statuses.map((status) => (
              <li key={status.label} data-state={status.state}>
                <i style={{ background: status.color }} />
                <span>{status.label}</span>
                <small>{status.state}</small>
              </li>
            ))}
          </ul>
          {!!artifacts.length && (
            <div className="point-artifacts">
              <strong>Weather artifacts</strong>
              {artifacts.map((artifact) => (
                <button
                  type="button"
                  key={artifact.id}
                  onClick={() => run({ type: 'selectArtifact', artifact })}
                >
                  {artifact.path.split('/').pop()}
                </button>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function segmentStops(status: DatasetPointStatus, index: number, segments: number) {
  const start = (index * 100) / segments
  const end = ((index + 1) * 100) / segments
  const middle = (start + end) / 2
  if (status.state === 'failed')
    return [`${status.color} ${start}% ${middle}%`, `var(--tone-danger-text) ${middle}% ${end}%`]
  if (status.state === 'gated')
    return [`${status.color} ${start}% ${middle}%`, `var(--color-text-muted) ${middle}% ${end}%`]
  if (status.state === 'unavailable') return [`var(--color-surface-raised) ${start}% ${end}%`]
  if (status.state === 'complete')
    return [`color-mix(in srgb, ${status.color} 72%, var(--tone-success-text)) ${start}% ${end}%`]
  return [`${status.color} ${start}% ${end}%`]
}

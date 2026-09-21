import { ChevronDown, ChevronUp, Layers3 } from 'lucide-react'
import { useState } from 'react'
import type { Schemas } from '../../api/client'

export type CoverageSetting = { id: string; opacity: number }

export function CoverageControl({
  layers,
  selected,
  onChange,
}: {
  layers: Schemas['CoverageLayer'][]
  selected: CoverageSetting[]
  onChange: (selected: CoverageSetting[]) => void
}) {
  const [open, setOpen] = useState(false)
  function move(index: number, direction: -1 | 1) {
    const next = [...selected]
    const destination = index + direction
    if (destination < 0 || destination >= next.length) return
    ;[next[index], next[destination]] = [next[destination], next[index]]
    onChange(next)
  }
  return (
    <div className="coverage-control">
      <button
        type="button"
        aria-label="Coverage layers"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Layers3 aria-hidden="true" /> Coverage
        {!!selected.length && <span>{selected.length}</span>}
      </button>
      {open && (
        <section aria-label="Documented coverage layers">
          <header>
            <strong>Documented coverage</strong>
            <small>Extents are not observed availability.</small>
          </header>
          {!layers.length && <p>Coverage metadata is unavailable.</p>}
          {layers.map((layer) => {
            const index = selected.findIndex((item) => item.id === layer.id)
            const setting = selected[index]
            return (
              <article key={layer.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={index >= 0}
                    onChange={(event) =>
                      onChange(
                        event.target.checked
                          ? [...selected, { id: layer.id, opacity: 0.32 }]
                          : selected.filter((item) => item.id !== layer.id),
                      )
                    }
                  />
                  <span>
                    <strong>{layer.label}</strong>
                    <small>
                      {layer.provider} · {layer.dataset}
                    </small>
                  </span>
                </label>
                <p>
                  {layer.kind === 'unknown'
                    ? 'No mapped extent; coverage is unknown.'
                    : `${layer.start_year ?? 'unknown'}–${layer.end_year ?? 'present'}`}
                </p>
                {layer.limitations?.map((limitation) => (
                  <p key={limitation} className="coverage-limitation">
                    {limitation}
                  </p>
                ))}
                <p>{layer.attribution}</p>
                <a href={layer.source_url} target="_blank" rel="noreferrer">
                  Source · observed {layer.observed_at.slice(0, 10)}
                </a>
                {setting && (
                  <div className="coverage-row-controls">
                    <label>
                      Opacity
                      <input
                        type="range"
                        min="0.05"
                        max="0.9"
                        step="0.05"
                        value={setting.opacity}
                        onChange={(event) =>
                          onChange(
                            selected.map((item) =>
                              item.id === layer.id
                                ? { ...item, opacity: Number(event.target.value) }
                                : item,
                            ),
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      aria-label={`Move ${layer.label} up`}
                      onClick={() => move(index, -1)}
                    >
                      <ChevronUp aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${layer.label} down`}
                      onClick={() => move(index, 1)}
                    >
                      <ChevronDown aria-hidden="true" />
                    </button>
                  </div>
                )}
              </article>
            )
          })}
        </section>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api, type Schemas, type WeatherRequest } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { validateDraft } from '../../api/input'
import { ListInput } from '../request/ListInput'

export function ExplorePanel() {
  const state = useApp()
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<Schemas['Location'][]>([])
  const [localError, setLocalError] = useState('')
  const location =
    !Array.isArray(state.draft.locations) && 'lat' in state.draft.locations
      ? state.draft.locations
      : null
  const sampling = {
    dx_km: state.draft.sampling?.dx_km ?? 25,
    dy_km: state.draft.sampling?.dy_km ?? 25,
    offset_x_km: state.draft.sampling?.offset_x_km ?? 0,
    offset_y_km: state.draft.sampling?.offset_y_km ?? 0,
    max_locations: state.draft.sampling?.max_locations ?? 1000,
  }

  useEffect(() => {
    const timer = window.setTimeout(() => run({ type: 'previewSpatial' }), 350)
    return () => window.clearTimeout(timer)
  }, [state.requestVersion])

  async function search() {
    try {
      setLocalError('')
      const result = await api.geocode(query)
      setPlaces(result.candidates)
    } catch (error) {
      setLocalError(String(error))
    }
  }

  const previewCurrent = state.spatialPreviewVersion === state.requestVersion
  const preview = state.spatialPreview

  return (
    <div className="stage-body">
      <section className="control-section">
        <h2>Place and geometry</h2>
        <label>
          Find a place
          <span className="inline">
            <input
              aria-label="Place name"
              placeholder="City or place"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void search()
              }}
            />
            <button type="button" onClick={() => void search()} disabled={!query.trim()}>
              Search
            </button>
          </span>
        </label>
        {places.length > 0 && (
          <div className="choices" aria-label="Place matches">
            {places.map((place) => (
              <button
                type="button"
                key={`${place.lat},${place.lon}`}
                onClick={() => {
                  run({ type: 'editQuery', patch: { locations: place } })
                  setPlaces([])
                }}
              >
                {place.name || 'Location'}
                <small>
                  {place.lat.toFixed(3)}, {place.lon.toFixed(3)}
                </small>
              </button>
            ))}
          </div>
        )}
        {location ? (
          <>
            <div className="two-col">
              <label>
                Latitude
                <input
                  type="number"
                  step="any"
                  value={location.lat}
                  onChange={(event) =>
                    run({
                      type: 'editQuery',
                      patch: { locations: { ...location, lat: Number(event.target.value) } },
                    })
                  }
                />
              </label>
              <label>
                Longitude
                <input
                  type="number"
                  step="any"
                  value={location.lon}
                  onChange={(event) =>
                    run({
                      type: 'editQuery',
                      patch: { locations: { ...location, lon: Number(event.target.value) } },
                    })
                  }
                />
              </label>
            </div>
            <label>
              Fixed standard-time offset
              <input
                type="number"
                step="60"
                value={location.standard_offset_minutes}
                onChange={(event) =>
                  run({
                    type: 'editQuery',
                    patch: {
                      locations: {
                        ...location,
                        standard_offset_minutes: Number(event.target.value),
                      },
                    },
                  })
                }
              />
              <small>Minutes from UTC; daylight saving time is not applied.</small>
            </label>
          </>
        ) : (
          <p className="notice">
            {Array.isArray(state.draft.locations)
              ? `${state.draft.locations.length} points selected`
              : 'Area geometry selected'}
          </p>
        )}
        <label>
          Import GeoJSON geometry
          <input
            type="file"
            accept=".json,.geojson"
            onChange={async (event) => {
              try {
                const file = event.target.files?.[0]
                if (!file) return
                if (file.size > 1_000_000) throw Error('GeoJSON exceeds 1 MB')
                const raw = JSON.parse(await file.text())
                const geometry = raw.type === 'Feature' ? raw.geometry : raw
                const next = { ...state.draft, locations: geometry }
                validateDraft(next)
                run({ type: 'editQuery', patch: { locations: geometry } })
                setLocalError('')
              } catch (error) {
                setLocalError(String(error))
              }
            }}
          />
        </label>
      </section>

      <section className="control-section">
        <h2>Weather period</h2>
        <label>
          Product
          <select
            value={state.draft.product}
            onChange={(event) =>
              run({
                type: 'editQuery',
                patch: {
                  product: event.target.value as WeatherRequest['product'],
                  years: ['tmy', 'tmyx', 'published'].includes(event.target.value) ? [] : [2024],
                  start: null,
                  end: null,
                  product_id: null,
                },
              })
            }
          >
            <option value="amy">Actual year</option>
            <option value="historical">Historical range</option>
            <option value="tmy">Published TMY</option>
            <option value="tmyx">Published TMYx</option>
            <option value="published">Other published file</option>
          </select>
        </label>
        {state.draft.product === 'amy' ? (
          <label>
            Years
            <ListInput
              value={state.draft.years?.join(',') || ''}
              onCommit={(value) =>
                run({
                  type: 'editQuery',
                  patch: {
                    years: value
                      .split(',')
                      .filter((item) => item.trim())
                      .map(Number),
                    start: null,
                    end: null,
                  },
                })
              }
            />
          </label>
        ) : state.draft.product === 'historical' ? (
          <div className="two-col">
            <label>
              From
              <input
                type="date"
                value={state.draft.start || ''}
                onChange={(event) =>
                  run({ type: 'editQuery', patch: { years: [], start: event.target.value } })
                }
              />
            </label>
            <label>
              Through
              <input
                type="date"
                value={state.draft.end || ''}
                onChange={(event) =>
                  run({ type: 'editQuery', patch: { years: [], end: event.target.value } })
                }
              />
            </label>
          </div>
        ) : (
          <label>
            Published product ID
            <input
              value={state.draft.product_id || ''}
              onChange={(event) =>
                run({ type: 'editQuery', patch: { product_id: event.target.value || null } })
              }
            />
          </label>
        )}
        {state.draft.product === 'amy' && (
          <label className="check-row">
            <input
              type="checkbox"
              checked={state.draft.skip_feb_29}
              onChange={(event) =>
                run({ type: 'editQuery', patch: { skip_feb_29: event.target.checked } })
              }
            />
            Produce an 8,760-row no-leap EPW
          </label>
        )}
      </section>

      <section className="control-section">
        <h2>Sampling grid</h2>
        <div className="two-col">
          <label>
            Horizontal spacing
            <input
              type="number"
              min="0.1"
              value={sampling.dx_km}
              onChange={(event) =>
                run({
                  type: 'editQuery',
                  patch: { sampling: { ...sampling, dx_km: Number(event.target.value) } },
                })
              }
            />
            <small>km</small>
          </label>
          <label>
            Vertical spacing
            <input
              type="number"
              min="0.1"
              value={sampling.dy_km}
              onChange={(event) =>
                run({
                  type: 'editQuery',
                  patch: { sampling: { ...sampling, dy_km: Number(event.target.value) } },
                })
              }
            />
            <small>km</small>
          </label>
          <label>
            Horizontal offset
            <input
              type="number"
              value={sampling.offset_x_km}
              onChange={(event) =>
                run({
                  type: 'editQuery',
                  patch: { sampling: { ...sampling, offset_x_km: Number(event.target.value) } },
                })
              }
            />
            <small>km</small>
          </label>
          <label>
            Vertical offset
            <input
              type="number"
              value={sampling.offset_y_km}
              onChange={(event) =>
                run({
                  type: 'editQuery',
                  patch: { sampling: { ...sampling, offset_y_km: Number(event.target.value) } },
                })
              }
            />
            <small>km</small>
          </label>
        </div>
        <div className={`sample-count ${preview?.executable === false ? 'warning' : ''}`}>
          {preview ? (
            <>
              <strong>{preview.total_count.toLocaleString()} sample points</strong>
              <span>
                {preview.planned_output_count.toLocaleString()} planned point-period outputs · limit{' '}
                {preview.execution_limit.toLocaleString()}
              </span>
              {!previewCurrent && <span>Updating authoritative preview…</span>}
              {preview.truncated && (
                <span>Showing the first {preview.returned_count.toLocaleString()} points.</span>
              )}
            </>
          ) : (
            <span>Calculating an authoritative sample preview…</span>
          )}
        </div>
      </section>
      {localError && (
        <p role="alert" className="error">
          {localError}
        </p>
      )}
    </div>
  )
}

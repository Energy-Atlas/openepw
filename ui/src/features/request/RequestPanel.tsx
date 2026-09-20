import { ListInput } from './ListInput'
import { validateDraft } from '../../api/input'
import { useState } from 'react'
import { api, type Schemas, type WeatherRequest } from '../../api/client'
import { useApp } from '../../app/store'
import { run } from '../../app/actions'
import { FutureForm } from './FutureForm'
import { PlanReview } from './PlanReview'
export function RequestPanel() {
  const s = useApp()
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<Schemas['Location'][]>([])
  const [raw, setRaw] = useState('')
  const [localError, setError] = useState('')
  const location =
    !Array.isArray(s.draft.locations) && 'lat' in s.draft.locations ? s.draft.locations : null
  async function search() {
    try {
      setError('')
      const result = await api.geocode(query)
      setPlaces(result.candidates)
    } catch (e) {
      setError(String(e))
    }
  }
  return (
    <section className="panel request-panel">
      <div className="eyebrow">WEATHER WORKSPACE</div>
      <h1>Build a weather request</h1>
      <p className="muted">Choose a place, review the source, keep the provenance.</p>
      <div className="segmented">
        <button aria-pressed={s.mode === 'weather'} onClick={() => s.setMode('weather')}>
          Existing weather
        </button>
        <button aria-pressed={s.mode === 'future'} onClick={() => s.setMode('future')}>
          Future weather
        </button>
      </div>
      {s.mode === 'future' ? (
        <FutureForm />
      ) : (
        <>
          <label>
            Find a place
            <div className="inline">
              <input
                aria-label="Place name"
                placeholder="City or place"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void search()
                }}
              />
              <button onClick={() => void search()} disabled={!query.trim()}>
                Search
              </button>
            </div>
          </label>
          {places.length > 0 && (
            <div className="choices">
              {places.map((p, i) => (
                <button
                  key={i}
                  onClick={() => {
                    s.edit({ locations: p })
                    setPlaces([])
                  }}
                >
                  {p.name || 'Location'}{' '}
                  <small>
                    {p.lat.toFixed(3)}, {p.lon.toFixed(3)}
                  </small>
                </button>
              ))}
              <small>Geocoding: Open-Meteo / GeoNames</small>
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
                    min="-90"
                    max="90"
                    value={location.lat}
                    onChange={(e) =>
                      s.edit({ locations: { ...location, lat: Number(e.target.value) } })
                    }
                  />
                </label>
                <label>
                  Longitude
                  <input
                    type="number"
                    step="any"
                    min="-180"
                    max="180"
                    value={location.lon}
                    onChange={(e) =>
                      s.edit({ locations: { ...location, lon: Number(e.target.value) } })
                    }
                  />
                </label>
              </div>
              <label>
                Standard offset (minutes from UTC)
                <input
                  type="number"
                  step="60"
                  value={location.standard_offset_minutes}
                  onChange={(e) =>
                    s.edit({
                      locations: { ...location, standard_offset_minutes: Number(e.target.value) },
                    })
                  }
                />
                <small>Fixed time, no DST. Whole-hour offsets only.</small>
              </label>
            </>
          ) : (
            <div className="notice">
              {Array.isArray(s.draft.locations)
                ? `${s.draft.locations.length} selected points`
                : 'Area selected on map'}
              <button
                onClick={() =>
                  s.edit({ locations: { lat: 42.44, lon: -76.5, standard_offset_minutes: 0 } })
                }
              >
                Use a point
              </button>
            </div>
          )}
          <div className="two-col">
            <label>
              Product
              <select
                value={s.draft.product}
                onChange={(e) =>
                  s.edit({
                    product: e.target.value as WeatherRequest['product'],
                    years: ['tmy', 'tmyx', 'published'].includes(e.target.value) ? [] : [2024],
                    start: null,
                    end: null,
                  })
                }
              >
                <option value="amy">Actual year</option>
                <option value="historical">Date range</option>
                <option value="tmy">Published TMY</option>
                <option value="tmyx">Published TMYx</option>
                <option value="published">Other published</option>
              </select>
            </label>
            <label>
              Provider
              <select
                value={s.draft.providers?.[0] || 'openmeteo'}
                onChange={(e) =>
                  s.edit({ providers: [e.target.value], dataset: null, product_id: null })
                }
              >
                {['openmeteo', 'pvgis', 'onebuilding', 'noaa', 'nsrdb', 'cds'].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
          </div>
          {s.draft.product === 'amy' ? (
            <label>
              Years (comma separated)
              <ListInput
                value={s.draft.years?.join(',') || ''}
                onCommit={(value) =>
                  s.edit({
                    years: value
                      .split(',')
                      .filter((v) => v.trim())
                      .map(Number),
                    start: null,
                    end: null,
                  })
                }
              />
            </label>
          ) : s.draft.product === 'historical' ? (
            <div className="two-col">
              <label>
                From
                <input
                  type="date"
                  value={s.draft.start || ''}
                  onChange={(e) => s.edit({ years: [], start: e.target.value })}
                />
              </label>
              <label>
                Through
                <input
                  type="date"
                  value={s.draft.end || ''}
                  onChange={(e) => s.edit({ years: [], end: e.target.value })}
                />
              </label>
            </div>
          ) : (
            <label>
              Published product ID
              <input
                value={s.draft.product_id || ''}
                placeholder="Provider product identifier, if required"
                onChange={(e) => s.edit({ product_id: e.target.value || null })}
              />
            </label>
          )}
          <details>
            <summary>Advanced request</summary>
            <label>
              Import GeoJSON Polygon
              <input
                type="file"
                accept=".json,.geojson"
                onChange={async (e) => {
                  try {
                    const file = e.target.files?.[0]
                    if (!file) return
                    if (file.size > 1_000_000) throw Error('GeoJSON exceeds 1 MB')
                    const raw = JSON.parse(await file.text())
                    const geometry = raw.type === 'Feature' ? raw.geometry : raw
                    const next = { ...s.draft, locations: geometry }
                    validateDraft(next)
                    s.edit({ locations: geometry })
                    setError('')
                  } catch (error) {
                    setError(String(error))
                  }
                }}
              />
            </label>
            <div className="two-col">
              <label>
                Grid spacing X (km)
                <input
                  type="number"
                  min="1"
                  value={s.draft.sampling?.dx_km ?? 25}
                  onChange={(e) =>
                    s.edit({
                      sampling: {
                        dx_km: Number(e.target.value),
                        dy_km: s.draft.sampling?.dy_km ?? 25,
                        offset_x_km: s.draft.sampling?.offset_x_km ?? 0,
                        offset_y_km: s.draft.sampling?.offset_y_km ?? 0,
                        max_locations: s.draft.sampling?.max_locations ?? 1000,
                      },
                    })
                  }
                />
              </label>
              <label>
                Grid spacing Y (km)
                <input
                  type="number"
                  min="1"
                  value={s.draft.sampling?.dy_km ?? 25}
                  onChange={(e) =>
                    s.edit({
                      sampling: {
                        dx_km: s.draft.sampling?.dx_km ?? 25,
                        dy_km: Number(e.target.value),
                        offset_x_km: s.draft.sampling?.offset_x_km ?? 0,
                        offset_y_km: s.draft.sampling?.offset_y_km ?? 0,
                        max_locations: s.draft.sampling?.max_locations ?? 1000,
                      },
                    })
                  }
                />
              </label>
            </div>
            <label>
              Dataset
              <input
                value={s.draft.dataset || ''}
                placeholder="Provider default"
                onChange={(e) => s.edit({ dataset: e.target.value || null })}
              />
            </label>
            <label>
              Missing variables
              <select
                value={s.draft.missing_policy}
                onChange={(e) => s.edit({ missing_policy: e.target.value as 'warn' | 'error' })}
              >
                <option value="warn">Return with warnings</option>
                <option value="error">Fail on missing variables</option>
              </select>
            </label>
            <p className="muted">
              Use JSON for point lists, polygon holes, sampling or explicit hybrid assignments.
              Backend validation applies.
            </p>
            <button onClick={() => setRaw(JSON.stringify(s.draft, null, 2))}>
              Load current JSON
            </button>
            <textarea
              aria-label="Request JSON"
              rows={8}
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
            />
            <button
              onClick={() => {
                try {
                  const next = JSON.parse(raw)
                  validateDraft(next)
                  s.edit(next)
                  setError('')
                } catch (e) {
                  setError(String(e))
                }
              }}
            >
              Apply JSON
            </button>
          </details>
          <div className="actions">
            <button disabled={s.busy} onClick={() => run({ type: 'discover' })}>
              Find sources
            </button>
            <button
              className="primary"
              disabled={s.busy}
              onClick={() => run({ type: 'planWeather' })}
            >
              Review plan
            </button>
          </div>
          {s.discovery && (
            <section>
              <h2>Source alternatives</h2>
              {s.discovery.candidates?.map((c) => (
                <article className="source-row" key={c.id}>
                  <strong>
                    {c.source.provider} · {c.source.dataset}
                  </strong>
                  <small>
                    {c.source.resolution_km
                      ? `${c.source.resolution_km} km source resolution`
                      : 'Resolution not reported'}
                  </small>
                  {!!c.requires_credentials?.length && (
                    <small>Requires {c.requires_credentials?.join(', ')}</small>
                  )}
                  {!!c.missing_fields?.length && (
                    <p className="warning">Missing: {c.missing_fields?.join(', ')}</p>
                  )}
                  {c.warnings?.map((w, i) => (
                    <small key={i}>{w}</small>
                  ))}
                </article>
              ))}
              {s.discovery.issues?.map((i, n) => (
                <p className="warning" key={n}>
                  {i.message}
                </p>
              ))}
            </section>
          )}
        </>
      )}
      {localError && (
        <p role="alert" className="error">
          {localError}
        </p>
      )}
      <PlanReview />
    </section>
  )
}

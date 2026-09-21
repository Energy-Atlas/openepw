import type { FutureRequest } from '../../api/client'
import { run } from '../../app/actions'
import { useApp } from '../../app/store'
import { ListInput } from './ListInput'

export function FutureForm() {
  const state = useApp()
  const future = state.future
  const morph = future.method === 'morph'
  const edit = (patch: Partial<FutureRequest>) => run({ type: 'editFuture', patch })

  return (
    <section className="control-section future-controls">
      <h2>Projection method</h2>
      <label>
        Method
        <select
          value={future.method}
          onChange={(event) =>
            edit({
              method: event.target.value as FutureRequest['method'],
              climate_scenario: event.target.value === 'morph' ? 'ssp245' : 'rcp85',
              reference_period: event.target.value === 'morph' ? [1985, 2014] : null,
              signals: null,
              extreme: {},
            })
          }
        >
          <option value="morph">CMIP6 monthly morphing</option>
          <option value="climate_profile">Coherent hourly climate profile</option>
        </select>
      </label>
      <p className="method-explainer">
        {morph
          ? 'Applies monthly climate-change signals while retaining the baseline sequence.'
          : 'Selects one coherent hourly WRF/CCSM4 trajectory at a published U.S. PUMA site.'}
      </p>
      <div className="two-col">
        <label>
          Scenario
          <select
            value={future.climate_scenario}
            onChange={(event) =>
              edit({ climate_scenario: event.target.value as FutureRequest['climate_scenario'] })
            }
          >
            {(morph ? ['ssp126', 'ssp245', 'ssp370', 'ssp585'] : ['rcp45', 'rcp85']).map(
              (scenario) => (
                <option key={scenario}>{scenario}</option>
              ),
            )}
          </select>
        </label>
        <label>
          Target year
          <input
            type="number"
            min="2020"
            max="2200"
            value={future.target_year || 2050}
            onChange={(event) =>
              edit({ target_year: Number(event.target.value), climate_period: null })
            }
          />
        </label>
      </div>
      <p className="period-readout">
        Climate window:{' '}
        {morph
          ? `${(future.target_year || 2050) - 14}–${(future.target_year || 2050) + 15}`
          : (future.target_year || 2050) >= 2085 && (future.target_year || 2050) <= 2094
            ? '2085–2094'
            : (future.target_year || 2050) >= 2045 && (future.target_year || 2050) <= 2054
              ? '2045–2054'
              : 'Unsupported target; use 2050 or 2090'}
      </p>
      {morph && (
        <div className="two-col">
          <label>
            Reference start
            <input
              type="number"
              value={future.reference_period?.[0] || 1985}
              onChange={(event) =>
                edit({
                  reference_period: [
                    Number(event.target.value),
                    future.reference_period?.[1] || 2014,
                  ],
                })
              }
            />
          </label>
          <label>
            Reference end
            <input
              type="number"
              value={future.reference_period?.[1] || 2014}
              onChange={(event) =>
                edit({
                  reference_period: [
                    future.reference_period?.[0] || 1985,
                    Number(event.target.value),
                  ],
                })
              }
            />
          </label>
        </div>
      )}
      <label>
        Profile
        <select
          value={future.profile}
          onChange={(event) => edit({ profile: event.target.value as FutureRequest['profile'] })}
        >
          <option value="typical">Typical</option>
          <option value="extreme">Extreme</option>
          <option value="ensemble">Ensemble</option>
        </select>
      </label>
      {future.profile === 'extreme' && !morph && (
        <div className="two-col">
          <label>
            Extreme type
            <select
              value={String(future.extreme?.type || 'hot')}
              onChange={(event) =>
                edit({ extreme: { ...future.extreme, type: event.target.value } })
              }
            >
              <option value="hot">Hot</option>
              <option value="cold">Cold</option>
            </select>
          </label>
          <label>
            Selection
            <select
              value={String(future.extreme?.mode || 'shock')}
              onChange={(event) =>
                edit({ extreme: { ...future.extreme, mode: event.target.value } })
              }
            >
              <option value="shock">Shock</option>
              <option value="persistence">Persistence</option>
            </select>
          </label>
        </div>
      )}
      {morph && (
        <details>
          <summary>Models, members, and local signals</summary>
          <label>
            Models
            <ListInput
              value={future.models?.join(',') || ''}
              placeholder="ACCESS-CM2"
              onCommit={(value) =>
                edit({
                  models: value
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            Members
            <ListInput
              value={future.members?.join(',') || ''}
              placeholder="r1i1p1f1"
              onCommit={(value) =>
                edit({
                  members: value
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            Monthly signal JSON
            <input
              type="file"
              accept=".json"
              disabled={state.busy}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) run({ type: 'uploadSignals', file })
              }}
            />
          </label>
          {future.signals && (
            <p>
              Local signals registered{' '}
              <button type="button" onClick={() => edit({ signals: null })}>
                Clear
              </button>
            </p>
          )}
        </details>
      )}
    </section>
  )
}

import { ListInput } from './ListInput'
import { useApp } from '../../app/store'
import { run } from '../../app/actions'
export function FutureForm() {
  const s = useApp(),
    f = s.future
  const morph = f.method === 'morph'
  return (
    <>
      <label>
        Baseline EPW
        <input
          type="file"
          accept=".epw"
          disabled={s.busy}
          onChange={(e) => {
            if (e.target.files?.[0]) run({ type: 'uploadBaseline', file: e.target.files[0] })
          }}
        />
      </label>
      <label>
        Or baseline artifact ID
        <input value={f.baseline} onChange={(e) => s.editFuture({ baseline: e.target.value })} />
      </label>
      {!f.baseline.trim() && (
        <p className="notice">
          A baseline EPW is required. Upload one above or select Use as baseline in Results.
        </p>
      )}
      <label>
        Method
        <select
          value={f.method}
          onChange={(e) =>
            s.editFuture({
              method: e.target.value as typeof f.method,
              climate_scenario: e.target.value === 'morph' ? 'ssp245' : 'rcp85',
              reference_period: e.target.value === 'morph' ? [1985, 2014] : null,
              signals: null,
              extreme: {},
            })
          }
        >
          <option value="morph">CMIP6 monthly morphing</option>
          <option value="climate_profile">Coherent hourly climate profile</option>
        </select>
      </label>
      <p className="notice">
        {morph
          ? 'Changes the baseline sequence using monthly climate signals.'
          : 'Selects a full WRF/CCSM4 trajectory at a published U.S. PUMA site. Your baseline supplies the location, not the hourly sequence.'}
      </p>
      <div className="two-col">
        <label>
          Scenario
          <select
            value={f.climate_scenario}
            onChange={(e) =>
              s.editFuture({ climate_scenario: e.target.value as typeof f.climate_scenario })
            }
          >
            {(morph ? ['ssp126', 'ssp245', 'ssp370', 'ssp585'] : ['rcp45', 'rcp85']).map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Target year
          <input
            type="number"
            value={f.target_year || 2050}
            onChange={(e) =>
              s.editFuture({ target_year: Number(e.target.value), climate_period: null })
            }
          />
        </label>
      </div>
      <p className="muted">
        Climate window:{' '}
        {morph
          ? `${(f.target_year || 2050) - 14}–${(f.target_year || 2050) + 15}`
          : (f.target_year || 2050) >= 2085 && (f.target_year || 2050) <= 2094
            ? '2085–2094'
            : (f.target_year || 2050) >= 2045 && (f.target_year || 2050) <= 2054
              ? '2045–2054'
              : 'Unsupported target — use 2050 or 2090'}
        . This is not a forecast.
      </p>
      {morph && (
        <div className="two-col">
          <label>
            Reference start
            <input
              type="number"
              value={f.reference_period?.[0] || 1985}
              onChange={(e) =>
                s.editFuture({
                  reference_period: [Number(e.target.value), f.reference_period?.[1] || 2014],
                })
              }
            />
          </label>
          <label>
            Reference end
            <input
              type="number"
              value={f.reference_period?.[1] || 2014}
              onChange={(e) =>
                s.editFuture({
                  reference_period: [f.reference_period?.[0] || 1985, Number(e.target.value)],
                })
              }
            />
          </label>
        </div>
      )}
      <label>
        Profile
        <select
          value={f.profile}
          onChange={(e) => s.editFuture({ profile: e.target.value as typeof f.profile })}
        >
          <option value="typical">Typical</option>
          <option value="extreme">Extreme</option>
          <option value="ensemble">Ensemble</option>
        </select>
        <small>Sampled weather is not implemented.</small>
      </label>
      {f.profile === 'extreme' && !morph && (
        <div className="two-col">
          <label>
            Type
            <select
              value={String(f.extreme?.type || 'hot')}
              onChange={(e) => s.editFuture({ extreme: { ...f.extreme, type: e.target.value } })}
            >
              <option>hot</option>
              <option>cold</option>
            </select>
          </label>
          <label>
            Statistic
            <select
              value={String(f.extreme?.mode || 'shock')}
              onChange={(e) => s.editFuture({ extreme: { ...f.extreme, mode: e.target.value } })}
            >
              <option>shock</option>
              <option>persistence</option>
            </select>
          </label>
        </div>
      )}
      {morph && (
        <details>
          <summary>Models and local signals</summary>
          <label>
            Models (comma separated)
            <ListInput
              value={f.models?.join(',') || ''}
              placeholder="ACCESS-CM2"
              onCommit={(value) =>
                s.editFuture({
                  models: value
                    .split(',')
                    .map((v) => v.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            Members
            <ListInput
              value={f.members?.join(',') || ''}
              placeholder="r1i1p1f1"
              onCommit={(value) =>
                s.editFuture({
                  members: value
                    .split(',')
                    .map((v) => v.trim())
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
              disabled={s.busy}
              onChange={(e) => {
                if (e.target.files?.[0]) run({ type: 'uploadSignals', file: e.target.files[0] })
              }}
            />
          </label>
          {f.signals && (
            <p>
              Signals registered{' '}
              <button onClick={() => s.editFuture({ signals: null })}>Clear</button>
            </p>
          )}
        </details>
      )}
      <button
        className="primary"
        disabled={s.busy || !f.baseline}
        onClick={() => run({ type: 'planFuture' })}
      >
        Review future plan
      </button>
    </>
  )
}

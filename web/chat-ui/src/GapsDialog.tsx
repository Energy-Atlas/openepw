import { useState } from 'react'
import { TickIcon } from './icons'

/** One way to cover a gap (`planning/gaps.py` gap_rows options). */
export type GapOption = {
  id: string; label: string; detail?: string; recommended?: boolean
  requires_credentials?: string[]; places?: number
}

/** One chosen source and variable group it lacks, as the data-gaps form shows it. */
export type GapRow = {
  id: string; number: number; label: string; source: string; places: number
  unresolved?: number; options: GapOption[]; selected?: string | null; notes?: string[]
}

/**
 * The data-gaps question: for each variable group a chosen source lacks, pick how to cover it
 * (another source, the station's own reports, or leave it missing), then confirm once. The
 * recommended option is selected; confirming sends the choice per row.
 */
export function GapsDialog({ rows, busy, onConfirm, onType }: {
  rows: GapRow[]
  busy?: boolean
  onConfirm: (choices: Record<string, string>) => void
  onType: () => void
}) {
  const [choices, setChoices] = useState<Record<string, string>>(() => Object.fromEntries(
    rows.map(row => [row.id, row.selected ?? row.options[0]?.id ?? ''])))
  return <section className="product-dialog gaps-dialog" aria-label="Cover data gaps">
    {rows.map(row => <fieldset key={row.id} className="gap-row">
      <legend className="option-group">{row.label}
        <span className="gap-source">{row.source} · {row.places} {row.places === 1 ? 'place' : 'places'}</span></legend>
      {row.options.map(option => <label key={option.id} className="gap-option">
        <input type="radio" name={`gap-${row.id}`} value={option.id} disabled={busy}
          checked={choices[row.id] === option.id}
          onChange={() => setChoices(current => ({ ...current, [row.id]: option.id }))} />
        <span className="gap-label">{option.label}
          {option.recommended && <span className="gap-recommended">Recommended</span>}
          {option.places !== undefined && option.places < row.places &&
            <span className="gap-places">at {option.places} of {row.places} places</span>}
          {option.detail && <span className="option-detail">{option.detail}</span>}</span>
      </label>)}
    </fieldset>)}
    <div className="dialog-actions">
      <button className="reply-alt" type="button" onClick={onType}>Other — type an answer</button>
      <button className="reply-primary confirm-products confirm-gaps" type="button" disabled={busy}
        onClick={() => onConfirm(choices)}><TickIcon />Confirm</button>
    </div>
  </section>
}

import { useState } from 'react'
import { InfoIcon, TickIcon } from './icons'

export type ProductOption = { id: string; label: string; detail?: string; group?: 'actual' | 'typical' }

/**
 * The weather-product question: tick one or more products of one kind, then confirm. Names only;
 * the extended description opens from the info icon. Map tags toggle the same selection.
 */
export function ProductDialog({ options, selected, note, busy, onToggle, onConfirm, onType }: {
  options: ProductOption[]
  selected: string[]
  note?: string
  busy?: boolean
  onToggle: (id: string) => void
  onConfirm: () => void
  onType: () => void
}) {
  // One popup outside the scrolling list, so it is never clipped by it.
  const [info, setInfo] = useState<{ id: string; text: string; top: number; left: number } | null>(null)
  const show = (option: ProductOption, target: HTMLElement) => {
    const box = target.getBoundingClientRect()
    // Opens just left of the dialog, over the map, beside the row it describes.
    const dialog = target.closest('.product-dialog')?.getBoundingClientRect()
    setInfo({ id: option.id, text: option.detail ?? '', top: box.top + box.height / 2, left: dialog?.left ?? box.left })
  }
  const groups = (['actual', 'typical'] as const).map(group => ({ group,
    items: options.filter(option => (option.group ?? 'actual') === group) })).filter(item => item.items.length)
  return <section className="product-dialog" aria-label="Choose weather products">
    <div className="product-list">
      {groups.map(({ group, items }) => <fieldset key={group}>
        <legend className="option-group">{group === 'actual' ? 'Actual year' : 'Typical year'}</legend>
        {items.map(option => <div key={option.id} className="product-row">
          <label>
            <input type="checkbox" checked={selected.includes(option.id)} disabled={busy}
              onChange={() => onToggle(option.id)} />
            <span>{option.label}</span>
          </label>
          {option.detail && <button type="button" className="info-button" aria-label={`About ${option.label}`}
            aria-describedby={info?.id === option.id ? 'product-info' : undefined}
            onMouseEnter={event => show(option, event.currentTarget)} onMouseLeave={() => setInfo(null)}
            onFocus={event => show(option, event.currentTarget)} onBlur={() => setInfo(null)}><InfoIcon /></button>}
        </div>)}
      </fieldset>)}
    </div>
    {note && <p className="dialog-note" role="status">{note}</p>}
    <div className="dialog-actions">
      <button className="reply-alt" type="button" onClick={onType}>Other — type an answer</button>
      <button className="reply-primary confirm-products" type="button" disabled={busy || !selected.length}
        onClick={onConfirm}><TickIcon />{selected.length > 1 ? `Confirm ${selected.length} products` : 'Confirm product'}</button>
    </div>
    {info && <div id="product-info" className="info-popup" role="tooltip"
      style={{ top: info.top, left: info.left }}>{info.text}</div>}
  </section>
}

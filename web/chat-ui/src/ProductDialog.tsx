import { useState } from 'react'
import { InfoIcon, TickIcon } from './icons'

export type ProductOption = {
  id: string; label: string; detail?: string; group?: 'actual' | 'typical'
  available?: number; unverified?: number; sites?: number
}

/** The hover message for a product's availability count across the selected sites. */
export function availabilityMessage(option: ProductOption): string {
  const message = `${option.label} is available at ${option.available ?? 0} of the ${option.sites} sites selected.`
  return option.unverified ? `${message} ${option.unverified} more ${option.unverified === 1 ? 'is' : 'are'} not verified in the catalog and checked when planning.` : message
}

/**
 * The weather-product question: tick any products, actual or typical year, then confirm. Names
 * only; the description opens from the info icon and, for several sites, a count column shows
 * where each product is available. Map tags toggle the same selection.
 */
export function ProductDialog({ options, selected, busy, onToggle, onConfirm, onType }: {
  options: ProductOption[]
  selected: string[]
  busy?: boolean
  onToggle: (id: string) => void
  onConfirm: () => void
  onType: () => void
}) {
  // One popup outside the list, placed just left of the dialog beside the row it describes.
  const [popup, setPopup] = useState<{ id: string; text: string; top: number; left: number } | null>(null)
  const show = (id: string, text: string, target: HTMLElement) => {
    const box = target.getBoundingClientRect()
    const dialog = target.closest('.product-dialog')?.getBoundingClientRect()
    setPopup({ id, text, top: box.top + box.height / 2, left: dialog?.left ?? box.left })
  }
  const hover = (id: string, text: string) => ({
    onMouseEnter: (event: React.MouseEvent<HTMLElement>) => show(id, text, event.currentTarget),
    onMouseLeave: () => setPopup(null),
    onFocus: (event: React.FocusEvent<HTMLElement>) => show(id, text, event.currentTarget),
    onBlur: () => setPopup(null),
    'aria-describedby': popup?.id === id ? 'product-popup' : undefined,
  })
  const counted = options.some(option => (option.sites ?? 0) > 1)
  const groups = (['actual', 'typical'] as const).map(group => ({ group,
    items: options.filter(option => (option.group ?? 'actual') === group) })).filter(item => item.items.length)
  return <section className="product-dialog" aria-label="Choose weather products">
    {groups.map(({ group, items }) => <fieldset key={group}>
      <legend className="option-group">{group === 'actual' ? 'Actual year' : 'Typical year'}</legend>
      {items.map(option => <div key={option.id} className="product-row">
        <label>
          <input type="checkbox" checked={selected.includes(option.id)} disabled={busy}
            onChange={() => onToggle(option.id)} />
          <span className="product-name">{option.label}</span>
        </label>
        {option.detail && <button type="button" className="info-button" aria-label={`About ${option.label}`}
          {...hover(`${option.id}:info`, option.detail)}><InfoIcon /></button>}
        {counted && <span className="site-count" tabIndex={0} aria-label={availabilityMessage(option)}
          {...hover(`${option.id}:count`, availabilityMessage(option))}>
          {option.available ?? 0} / {option.sites}</span>}
      </div>)}
    </fieldset>)}
    <div className="dialog-actions">
      <button className="reply-alt" type="button" onClick={onType}>Other — type an answer</button>
      <button className="reply-primary confirm-products" type="button" disabled={busy || !selected.length}
        onClick={onConfirm}><TickIcon />{selected.length > 1 ? `Confirm ${selected.length} products` : 'Confirm product'}</button>
    </div>
    {popup && <div id="product-popup" className="info-popup" role="tooltip"
      style={{ top: popup.top, left: popup.left }}>{popup.text}</div>}
  </section>
}

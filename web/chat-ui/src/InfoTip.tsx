import { useState, type ReactNode } from 'react'
import { InfoIcon } from './icons'

/**
 * An info button whose extended text opens on hover or focus, beside the button. The popup is
 * fixed-positioned so a scrolling parent never clips it.
 */
export function InfoTip({ label, children, side = 'right' }: { label: string; children: ReactNode; side?: 'left' | 'right' }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null)
  const show = (target: HTMLElement) => {
    const box = target.getBoundingClientRect()
    setAt({ top: box.top + box.height / 2, left: side === 'right' ? box.right : box.left })
  }
  return <>
    <button type="button" className="info-button" aria-label={label}
      onMouseEnter={event => show(event.currentTarget)} onMouseLeave={() => setAt(null)}
      onFocus={event => show(event.currentTarget)} onBlur={() => setAt(null)}><InfoIcon /></button>
    {at && <div className={`info-popup ${side}`} role="tooltip" style={{ top: at.top, left: at.left }}>{children}</div>}
  </>
}

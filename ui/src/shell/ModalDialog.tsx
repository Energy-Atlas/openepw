import { createPortal } from 'react-dom'
import { useEffect, useRef, type ReactNode, type RefObject } from 'react'

export function ModalDialog({
  children,
  className,
  role = 'dialog',
  ariaLabel,
  labelledBy,
  onClose,
  restoreFocus,
}: {
  children: ReactNode
  className: string
  role?: 'dialog' | 'alertdialog'
  ariaLabel?: string
  labelledBy?: string
  onClose: () => void
  restoreFocus?: RefObject<HTMLElement | null>
}) {
  const dialog = useRef<HTMLDivElement>(null)
  const previousFocus = useRef<HTMLElement | null>(null)

  useEffect(() => {
    previousFocus.current = restoreFocus?.current ?? (document.activeElement as HTMLElement | null)
    const root = document.getElementById('root')
    if (root) root.inert = true
    const focusable = getFocusable(dialog.current)
    ;(
      dialog.current?.querySelector<HTMLElement>('[data-autofocus]') ??
      focusable[0] ??
      dialog.current
    )?.focus()
    return () => {
      if (root) root.inert = false
      const target = restoreFocus?.current ?? previousFocus.current
      queueMicrotask(() => target?.focus())
    }
  }, [restoreFocus])

  return createPortal(
    <div
      ref={dialog}
      className={className}
      role={role}
      aria-modal="true"
      aria-label={ariaLabel}
      aria-labelledby={labelledBy}
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          onClose()
          return
        }
        if (event.key !== 'Tab') return
        const focusable = getFocusable(dialog.current)
        if (!focusable.length) {
          event.preventDefault()
          dialog.current?.focus()
          return
        }
        const current = document.activeElement
        const index = focusable.indexOf(current as HTMLElement)
        const next = event.shiftKey
          ? focusable[(index <= 0 ? focusable.length : index) - 1]
          : focusable[(index + 1) % focusable.length]
        event.preventDefault()
        next.focus()
      }}
    >
      {children}
    </div>,
    document.body,
  )
}

function getFocusable(host: HTMLElement | null) {
  if (!host) return []
  return [
    ...host.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ]
}

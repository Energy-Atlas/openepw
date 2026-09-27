// Small line icons shared by the chat and the map; each has an accessible label on its button.

const iconProps = { viewBox: '0 0 24 24', width: 18, height: 18, fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.6, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

/** Enter key glyph for sending a message. */
export function EnterIcon() {
  return <svg {...iconProps}><path d="M19 5v7a3 3 0 0 1-3 3H6" /><path d="m9 11-4 4 4 4" /></svg>
}

/** Tick glyph for confirming a choice or typed answer. */
export function TickIcon() {
  return <svg {...iconProps}><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
}

export function DownloadIcon() {
  return <svg {...iconProps}><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></svg>
}

export function BackIcon() {
  return <svg {...iconProps}><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></svg>
}

export function RestartIcon() {
  return <svg {...iconProps}><path d="M4 4v6h6" /><path d="M5.5 15a7 7 0 1 0 1.6-7.3L4 10" /></svg>
}

/** Wrench glyph for tool-call lines; the viewBox is cropped square around the path so it centres. */
export function ToolIcon() {
  return <svg viewBox="2.08 4.72 16.4 16.4" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.1"
    strokeLinecap="round" strokeLinejoin="round">
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.1L3.6 17.1a1.8 1.8 0 0 0 2.5 2.5l5.7-5.7a4 4 0 0 0 5.1-5.4l-2.4 2.4-2.3-.4-.4-2.3z" />
  </svg>
}

/** Minimize glyph: hides a popup without clearing its selection. */
export function MinimizeIcon() {
  return <svg {...iconProps} width={14} height={14}><path d="M6 12h12" /></svg>
}

/** Info glyph: opens a product's extended description. */
export function InfoIcon() {
  return <svg {...iconProps} width={16} height={16}><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5" /><path d="M12 7.6v.1" /></svg>
}

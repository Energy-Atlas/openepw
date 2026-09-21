import type { PanelSizes } from '../app/store'

export type Drawer = 'controls' | 'agent' | null
export type ResizablePanel = keyof PanelSizes

const limits: Record<ResizablePanel, readonly [number, number]> = {
  controls: [280, 520],
  agent: [280, 520],
  inspector: [180, 520],
}

export function clampPanelSize(panel: ResizablePanel, size: number) {
  const [minimum, maximum] = limits[panel]
  return Math.min(maximum, Math.max(minimum, Math.round(size)))
}

export function nextDrawer(current: Drawer, requested: Exclude<Drawer, null>): Drawer {
  return current === requested ? null : requested
}

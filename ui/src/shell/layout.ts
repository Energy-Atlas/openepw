export const narrowBreakpoint = 820

export function isNarrow(width = window.innerWidth) {
  return width < narrowBreakpoint
}

export function resizeFromPointer(
  side: 'left' | 'right',
  origin: number,
  initial: number,
  pointer: number,
) {
  return initial + (side === 'left' ? pointer - origin : origin - pointer)
}

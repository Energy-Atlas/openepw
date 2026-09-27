/** Screen-space placement for station name pills, shared across NOAA and OneBuilding. */

export type LabelInput = { id: string; x: number; y: number; text: string; prefix?: string; color: string; width: number; height: number }
export type PlacedLabel = LabelInput & { anchor: { x: number; y: number }; callout: boolean }
type Box = { x: number; y: number; width: number; height: number }

const MARKER_RADIUS = 4
const GAP = 7
const CELL = 48
// Beside the marker first; further rings are drawn with a callout line back to the station.
const RINGS = [0, 22, 44, 70]
const DIRECTIONS = [[0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [-1, 1], [1, -1], [-1, -1]]

function hits(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

/** Buckets boxes by screen cell so each test only looks at nearby markers and labels. */
class Grid {
  private cells = new Map<string, Box[]>()

  private keys(box: Box): string[] {
    const keys = []
    for (let cx = Math.floor(box.x / CELL); cx <= Math.floor((box.x + box.width) / CELL); cx++)
      for (let cy = Math.floor(box.y / CELL); cy <= Math.floor((box.y + box.height) / CELL); cy++) keys.push(`${cx}:${cy}`)
    return keys
  }

  add(box: Box) {
    for (const key of this.keys(box)) this.cells.set(key, [...(this.cells.get(key) ?? []), box])
  }

  collides(box: Box): boolean {
    return this.keys(box).some(key => (this.cells.get(key) ?? []).some(other => hits(box, other)))
  }
}

/** Candidate top-left corners around a point, nearest first. */
function candidates(item: LabelInput): Array<{ x: number; y: number; callout: boolean }> {
  const result = []
  for (const [ring, distance] of RINGS.entries()) {
    for (const [dx, dy] of DIRECTIONS) {
      if (ring === 0 && dx !== 0 && dy !== 0) continue     // diagonals only once moved out
      const cx = item.x + dx * (distance + GAP + (dx ? item.width / 2 : 0))
      const cy = item.y + dy * (distance + GAP + (dy ? item.height / 2 : 0))
      result.push({ x: cx - item.width / 2, y: cy - item.height / 2, callout: ring > 0 })
    }
  }
  return result
}

/** Greedy placement in input order (put the most important first); drops labels with no room. */
export function placeLabels(items: LabelInput[], markers: Array<{ x: number; y: number }>,
  size: { width: number; height: number }, options: { max?: number; obstacles?: Box[] } = {}): PlacedLabel[] {
  const max = options.max ?? 150
  const placed: PlacedLabel[] = []
  const occupied = new Grid()
  for (const box of options.obstacles ?? []) occupied.add(box)
  for (const point of [...markers, ...items]) {
    occupied.add({ x: point.x - MARKER_RADIUS, y: point.y - MARKER_RADIUS,
      width: MARKER_RADIUS * 2, height: MARKER_RADIUS * 2 })
  }
  for (const item of items) {
    if (placed.length >= max) break
    for (const spot of candidates(item)) {
      const box = { x: spot.x, y: spot.y, width: item.width, height: item.height }
      if (box.x < 0 || box.y < 0 || box.x + box.width > size.width || box.y + box.height > size.height) continue
      if (occupied.collides(box)) continue
      occupied.add(box)
      placed.push({ ...item, ...box, anchor: { x: item.x, y: item.y }, callout: spot.callout })
      break
    }
  }
  return placed
}

/** Where a callout line from the station meets the pill's edge. */
export function calloutEnd(label: PlacedLabel): { x: number; y: number } {
  return { x: Math.min(Math.max(label.anchor.x, label.x), label.x + label.width),
    y: Math.min(Math.max(label.anchor.y, label.y), label.y + label.height) }
}

import { describe, expect, it } from 'vitest'
import { placeLabels, type LabelInput } from '../src/map/labels'

const size = { width: 800, height: 600 }
const input = (id: string, x: number, y: number, width = 60): LabelInput =>
  ({ id, x, y, text: id, color: '#000', width, height: 16 })

function overlaps(a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number }) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

describe('station label placement', () => {
  it('puts a lone label beside its marker without a callout', () => {
    const [label] = placeLabels([input('A', 400, 300)], [], size)
    expect(label.callout).toBe(false)
    expect(Math.abs(label.x + label.width / 2 - 400)).toBeLessThan(label.width)
    expect(Math.abs(label.y - 300)).toBeLessThan(30)
  })

  it('moves crowded labels out with callouts and never overlaps them', () => {
    const crowd = [input('A', 400, 300), input('B', 404, 302), input('C', 398, 305), input('D', 402, 298)]
    const placed = placeLabels(crowd, [], size)
    expect(placed).toHaveLength(4)
    expect(placed.filter(label => label.callout).length).toBeGreaterThanOrEqual(2)
    for (const a of placed) for (const b of placed) if (a !== b) expect(overlaps(a, b)).toBe(false)
    for (const label of placed) expect(label.anchor).toEqual({ x: crowd.find(item => item.id === label.id)!.x,
      y: crowd.find(item => item.id === label.id)!.y })
  })

  it('keeps labels off other markers and inside the map, and drops what does not fit', () => {
    const markers = [{ x: 400, y: 318 }, { x: 400, y: 282 }]
    const [label] = placeLabels([input('A', 400, 300)], markers, size)
    for (const marker of markers) expect(overlaps(label, { x: marker.x - 4, y: marker.y - 4, width: 8, height: 8 })).toBe(false)
    const edge = placeLabels([input('E', 795, 5)], [], size)
    expect(edge[0].x + edge[0].width).toBeLessThanOrEqual(size.width)
    expect(edge[0].y).toBeGreaterThanOrEqual(0)
    const wall = Array.from({ length: 400 }, (_, index) => input(`W${index}`, 400, 300, 200))
    expect(placeLabels(wall, [], size).length).toBeLessThan(400)
  })

  it('caps the number of labels', () => {
    const many = Array.from({ length: 500 }, (_, index) => input(`P${index}`, (index % 25) * 32 + 10, Math.floor(index / 25) * 30 + 10, 20))
    expect(placeLabels(many, [], size, { max: 50 }).length).toBeLessThanOrEqual(50)
  })

  it('keeps station names off the product availability tags', () => {
    const tag = { x: 390, y: 285, width: 120, height: 30 }
    const [label] = placeLabels([input('A', 400, 300)], [], size, { obstacles: [tag] })
    expect(overlaps(label, tag)).toBe(false)
  })
})

import { it, expect } from 'vitest'
import {
  canFinish,
  geometry,
  measureSelection,
  moveVertex,
  removeVertex,
  undoVertex,
} from './selection'
it('requires enough vertices and closes polygon rings', () => {
  expect(() =>
    geometry('polygon', [
      [1, 2],
      [2, 3],
    ]),
  ).toThrow()
  expect(
    geometry('polygon', [
      [1, 2],
      [2, 3],
      [3, 2],
    ]),
  ).toEqual({
    type: 'Polygon',
    coordinates: [
      [
        [1, 2],
        [2, 3],
        [3, 2],
        [1, 2],
      ],
    ],
  })
})
it('normalizes a box and bounds point lists', () => {
  expect(
    geometry('bbox', [
      [3, 4],
      [1, 2],
    ]),
  ).toEqual({ west: 1, south: 2, east: 3, north: 4 })
  expect(() => geometry('points', [])).toThrow()
})

it('supports reversible keyboard-friendly vertex edits', () => {
  const vertices: [number, number][] = [
    [-76.5, 42.4],
    [-76.4, 42.5],
  ]
  expect(moveVertex(vertices, 0, [-76.45, 42.45])).toEqual([
    [-76.45, 42.45],
    [-76.4, 42.5],
  ])
  expect(removeVertex(vertices, 0)).toEqual([[-76.4, 42.5]])
  expect(undoVertex(vertices)).toEqual([[-76.5, 42.4]])
  expect(vertices).toHaveLength(2)
})

it('reports finish readiness and a live measurement', () => {
  expect(canFinish('point', [[0, 0]])).toBe(true)
  expect(canFinish('bbox', [[0, 0]])).toBe(false)
  expect(
    canFinish('polygon', [
      [0, 0],
      [1, 0],
      [1, 1],
    ]),
  ).toBe(true)
  expect(
    measureSelection('bbox', [
      [0, 0],
      [1, 1],
    ]),
  ).toMatch(/km²/)
  expect(
    measureSelection('polygon', [
      [0, 0],
      [1, 0],
      [1, 1],
    ]),
  ).toMatch(/km²/)
  expect(
    measureSelection('points', [
      [0, 0],
      [1, 1],
    ]),
  ).toBe('2 points')
})

it('recovers editable vertices from every applied geometry and round-trips them', async () => {
  const { applyShape, editableShape } = await import('./selection')
  const polygon = {
    type: 'Polygon',
    coordinates: [
      [
        [1, 2],
        [2, 3],
        [3, 2],
        [1, 2],
      ],
    ],
  }
  const box = { west: -1, south: -2, east: 3, north: 4 }
  const point = { lat: 42, lon: -76, standard_offset_minutes: -300, name: 'Ithaca' }
  const list = [
    { lat: 1, lon: 2, standard_offset_minutes: 60, id: 'a' },
    { lat: 3, lon: 4, standard_offset_minutes: 0, id: 'b' },
  ]
  for (const original of [polygon, box, point, list]) {
    const shape = editableShape(original)!
    expect(applyShape(original, shape.mode, shape.vertices)).toEqual(original)
  }
  expect(editableShape(polygon)).toEqual({
    mode: 'polygon',
    vertices: [
      [1, 2],
      [2, 3],
      [3, 2],
    ],
  })
  expect(applyShape(point, 'point', [[-75, 43]])).toEqual({ ...point, lat: 43, lon: -75 })
})

it('refuses to edit shapes whose holes or parts would be lost', async () => {
  const { editableShape } = await import('./selection')
  const ring = [
    [0, 0],
    [4, 0],
    [4, 4],
    [0, 0],
  ]
  expect(editableShape({ type: 'Polygon', coordinates: [ring, ring] })).toBeNull()
  expect(editableShape({ type: 'MultiPolygon', coordinates: [[ring]] })).toBeNull()
  expect(editableShape([])).toBeNull()
})

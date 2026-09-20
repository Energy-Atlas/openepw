export type DrawMode = 'point' | 'points' | 'bbox' | 'polygon'
export type Position = [number, number]
export function geometry(mode: DrawMode, vertices: Position[]) {
  if (
    !vertices.length ||
    vertices.some(
      ([x, y]) =>
        !Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 180 || Math.abs(y) > 90,
    )
  )
    throw Error('Select valid coordinates')
  const points = vertices.map(([lon, lat]) => ({ lat, lon, standard_offset_minutes: 0 }))
  if (mode === 'point') return points[0]
  if (mode === 'points') return points
  if (mode === 'bbox') {
    if (vertices.length !== 2) throw Error('Select two opposite corners')
    const [a, b] = vertices
    return {
      west: Math.min(a[0], b[0]),
      south: Math.min(a[1], b[1]),
      east: Math.max(a[0], b[0]),
      north: Math.max(a[1], b[1]),
    }
  }
  if (vertices.length < 3) throw Error('A polygon needs at least three vertices')
  return { type: 'Polygon' as const, coordinates: [[...vertices, vertices[0]]] }
}

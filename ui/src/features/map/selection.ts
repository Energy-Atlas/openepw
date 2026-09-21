export type DrawMode = 'point' | 'points' | 'bbox' | 'polygon'
export type Position = [number, number]

export function canFinish(mode: DrawMode, vertices: Position[]) {
  return (
    (mode === 'point' && vertices.length === 1) ||
    (mode === 'points' && vertices.length > 0) ||
    (mode === 'bbox' && vertices.length === 2) ||
    (mode === 'polygon' && vertices.length >= 3)
  )
}

export function undoVertex(vertices: Position[]) {
  return vertices.slice(0, -1)
}

export function removeVertex(vertices: Position[], index: number) {
  return vertices.filter((_, candidate) => candidate !== index)
}

export function moveVertex(vertices: Position[], index: number, position: Position) {
  return vertices.map((vertex, candidate) => (candidate === index ? position : vertex))
}

const EARTH_KM = 6371.0088
const radians = (value: number) => (value * Math.PI) / 180

function distance(a: Position, b: Position) {
  const dLat = radians(b[1] - a[1])
  const dLon = radians(b[0] - a[0])
  const lat1 = radians(a[1])
  const lat2 = radians(b[1])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_KM * Math.asin(Math.sqrt(h))
}

export function measureSelection(mode: DrawMode, vertices: Position[]) {
  if (mode === 'point') return vertices.length ? '1 point' : 'No point'
  if (mode === 'points') return `${vertices.length} point${vertices.length === 1 ? '' : 's'}`
  if (!canFinish(mode, vertices)) return 'Incomplete geometry'
  if (mode === 'bbox') {
    const [a, b] = vertices
    const width = distance([a[0], (a[1] + b[1]) / 2], [b[0], (a[1] + b[1]) / 2])
    const height = distance([(a[0] + b[0]) / 2, a[1]], [(a[0] + b[0]) / 2, b[1]])
    return `${Math.round(width * height).toLocaleString()} km²`
  }
  const ring = [...vertices, vertices[0]]
  const meanLat = radians(vertices.reduce((sum, vertex) => sum + vertex[1], 0) / vertices.length)
  const projected = ring.map(([lon, lat]) => [
    radians(lon) * EARTH_KM * Math.cos(meanLat),
    radians(lat) * EARTH_KM,
  ])
  const area = Math.abs(
    projected.slice(0, -1).reduce((sum, [x, y], index) => {
      const [nextX, nextY] = projected[index + 1]
      return sum + x * nextY - nextX * y
    }, 0) / 2,
  )
  return `${Math.round(area).toLocaleString()} km²`
}
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

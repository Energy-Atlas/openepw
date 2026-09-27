/** Approximate direct-sun footprint projection in a small local map district. */
import polygonClipping from 'polygon-clipping'
export type SunVector = { elevationDeg: number; azimuthDeg: number }
export type Coordinate = [number, number]
export type BuildingShape = { ring: Coordinate[]; height: number; ground?: number }
export type RoofShade = { rings: Coordinate[][]; height: number }

export function projectShadowRing(
  footprint: Coordinate[], heightMetres: number, sun: SunVector,
): Coordinate[] | null {
  if (sun.elevationDeg <= 0 || heightMetres <= 0 || footprint.length < 4) return null
  const length = Math.min(2000, heightMetres / Math.tan(sun.elevationDeg * Math.PI / 180))
  const azimuth = sun.azimuthDeg * Math.PI / 180
  const east = -Math.sin(azimuth) * length
  const north = -Math.cos(azimuth) * length
  return footprint.map(([lon, lat]) => [
    lon + east / (111_320 * Math.max(0.1, Math.cos(lat * Math.PI / 180))),
    lat + north / 111_320,
  ])
}

/** Intersect a projected upper roof with a lower roof, rather than coloring whole buildings. */
export function roofShadow(source: BuildingShape, target: BuildingShape, sun: SunVector): RoofShade[] {
  const sourceTop = source.height + (source.ground ?? 0)
  const targetTop = target.height + (target.ground ?? 0)
  if (sourceTop <= targetTop || sun.elevationDeg <= 0) return []
  const projected = projectShadowRing(source.ring, sourceTop - targetTop, sun)
  if (!projected) return []
  const intersection = polygonClipping.intersection([projected], [target.ring])
  return intersection.map(polygon => ({
    rings: polygon.map(ring => ring.map(([lon, lat]) => [lon, lat] as Coordinate)),
    height: target.height,
  }))
}

/** Ray-march from a ground cell toward the sun against displayed terrain heights. */
export function terrainOccluded(
  east: number, north: number, sample: (east: number, north: number) => number | null,
  sun: SunVector, rangeMetres: number, stepMetres = 5,
): boolean {
  if (sun.elevationDeg <= 0) return false
  const base = sample(east, north)
  if (base === null) return false
  const azimuth = sun.azimuthDeg * Math.PI / 180
  const rise = Math.tan(sun.elevationDeg * Math.PI / 180)
  for (let distance = stepMetres; distance <= rangeMetres; distance += stepMetres) {
    const elevation = sample(east + distance * Math.sin(azimuth),
      north + distance * Math.cos(azimuth))
    if (elevation !== null && elevation > base + distance * rise) return true
  }
  return false
}

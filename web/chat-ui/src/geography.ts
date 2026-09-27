type Point = { lat: number; lon: number; name?: string }
type Polygon = { type: 'Polygon'; coordinates: number[][][] }
type BoundingBox = { west: number; south: number; east: number; north: number }
export type WeatherGeography = Point | Point[] | Polygon | BoundingBox

export function geojsonGeography(value: unknown): WeatherGeography {
  if (!value || typeof value !== 'object') throw new Error('GeoJSON must be an object')
  const root = value as Record<string, unknown>
  if (root.crs && JSON.stringify(root.crs) !== JSON.stringify({ type: 'name', properties: { name: 'EPSG:4326' } })) {
    throw new Error('GeoJSON coordinates must use WGS84 longitude, latitude')
  }
  const features = root.type === 'FeatureCollection' ? root.features
    : root.type === 'Feature' ? [root] : [{ geometry: root, properties: {} }]
  if (!Array.isArray(features) || !features.length || features.length > 1000) {
    throw new Error('GeoJSON needs 1–1000 point features or one polygon')
  }
  const geometries = features.map(feature => (feature as Record<string, unknown>).geometry as Record<string, unknown>)
  if (geometries.every(geometry => geometry?.type === 'Point')) {
    return geometries.map((geometry, index) => {
      const coords = geometry.coordinates as number[]
      if (!Array.isArray(coords) || coords.length < 2) throw new Error('Invalid Point coordinates')
      return { lon: coords[0], lat: coords[1],
        name: String(((features[index] as Record<string, unknown>).properties as Record<string, unknown> | undefined)?.name ?? '').slice(0, 100) || undefined }
    })
  }
  if (geometries.length !== 1 || geometries[0]?.type !== 'Polygon') {
    throw new Error('Upload one Polygon or a collection of Points; MultiPolygon is unsupported')
  }
  const coordinates = geometries[0].coordinates
  if (!Array.isArray(coordinates) || !coordinates.length || coordinates.some(ring =>
    !Array.isArray(ring) || ring.length > 500)) {
    throw new Error('Polygon needs rings with at most 500 vertices each')
  }
  return { type: 'Polygon', coordinates: coordinates as number[][][] }
}

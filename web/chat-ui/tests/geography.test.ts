import { describe, expect, it } from 'vitest'
import { geojsonGeography } from '../src/geography'

describe('GeoJSON geography conversion', () => {
  it('keeps holes for the canonical service validator', () => {
    const polygon = { type: 'Polygon', coordinates: [
      [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
      [[.5, .5], [1, .5], [1, 1], [.5, 1], [.5, .5]],
    ] }
    expect((geojsonGeography(polygon) as typeof polygon).coordinates).toHaveLength(2)
  })

  it('maps a point collection and rejects unsupported CRS', () => {
    const collection = { type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-71, 42] }, properties: { name: 'A' } },
    ] }
    expect(geojsonGeography(collection)).toEqual([{ lon: -71, lat: 42, name: 'A' }])
    expect(() => geojsonGeography({ ...collection, crs: { type: 'name', properties: { name: 'EPSG:3857' } } }))
      .toThrow('WGS84')
  })
})

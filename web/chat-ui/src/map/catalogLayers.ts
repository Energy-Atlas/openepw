import type { Feature, FeatureCollection, Geometry } from 'geojson'
import type { CatalogLayer } from '../types'

const colors: Record<string, string> = {
  noaa: '#237e8b', onebuilding: '#d69b36', nsrdb: '#3f6fd9', pvgis: '#8a5cc2',
  era5: '#647782', 'era5-land': '#659777',
}

export function layerColor(id: string): string { return colors[id] ?? '#647782' }

/** True when every requested year falls in one of the station's reported-year ranges. */
export function reportsEveryYear(ranges: number[][], years: number[]): boolean {
  return years.every(year => ranges.some(([first, last]) => first <= year && year <= last))
}

function box([west, south, east, north]: number[]): Geometry {
  return { type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] }
}

/** Documentary catalog context as GeoJSON; nothing here is point eligibility. */
export function catalogFeatures(layer: CatalogLayer, years: number[] = []): FeatureCollection {
  const features: Feature[] = []
  const feature = (geometry: Geometry, properties: Record<string, unknown> = {}) =>
    features.push({ type: 'Feature', geometry, properties })
  if (layer.kind === 'stations') {
    for (const [lon, lat, id, ranges] of layer.points ?? []) {
      if (years.length && !reportsEveryYear(ranges as number[][], years)) continue
      feature({ type: 'Point', coordinates: [lon, lat] }, { id })
    }
  } else if (layer.kind === 'sites') {
    for (const [lon, lat, label, period, position] of layer.points ?? []) {
      feature({ type: 'Point', coordinates: [lon, lat] }, { label, period,
        approximate: position !== 'published' && position !== 'consensus' })
    }
  } else if (layer.kind === 'cells') {
    for (const rect of layer.rects ?? []) feature(box(rect))
  } else if (layer.kind === 'area') {
    if (layer.polygon?.length) feature({ type: 'Polygon', coordinates: [layer.polygon] })
    for (const probe of layer.probes ?? []) feature({ type: 'Point', coordinates: probe }, { probe: true })
  } else if (layer.bounds) {
    feature(box(layer.bounds))
  }
  return { type: 'FeatureCollection', features }
}

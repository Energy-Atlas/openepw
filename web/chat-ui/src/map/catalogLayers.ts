import type { Feature, FeatureCollection, Geometry } from 'geojson'
import type { AddLayerObject, ExpressionSpecification, FilterSpecification } from 'maplibre-gl'
import type { CatalogLayer } from '../types'

/**
 * One map palette built from the approved OpenEPW tokens. Amber is the single accent and
 * belongs only to what the user chose; catalog layers separate by shape first, hue second.
 */
export const MAP_PALETTE = {
  HERO: '#d69b36',            // selected location, drawn/accepted geography
  OBSERVED: '#237e8b',        // NOAA station records (measured actual years)
  PUBLISHED: '#173849',       // OneBuilding published files; geocoder candidate rings
  PUBLISHED_FAINT: 'rgba(23,56,73,.45)',
  REGION: '#647782',          // NSRDB grid and PVGIS region
  EXTENT: 'rgba(100,119,130,.55)',
} as const

const swatches: Record<CatalogLayer['kind'], { color: string; shape: 'dot' | 'fill' | 'outline' | 'dash' }> = {
  stations: { color: MAP_PALETTE.OBSERVED, shape: 'dot' },
  sites: { color: MAP_PALETTE.PUBLISHED, shape: 'dot' },
  cells: { color: MAP_PALETTE.REGION, shape: 'fill' },
  area: { color: MAP_PALETTE.REGION, shape: 'outline' },
  extent: { color: MAP_PALETTE.EXTENT, shape: 'dash' },
}

export function layerSwatch(kind: CatalogLayer['kind']) { return swatches[kind] }

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
    // A documented extent only carries its latitude limits; draw those as rims, not a globe-wide fill.
    const [west, south, east, north] = layer.bounds
    feature({ type: 'MultiLineString', coordinates: [[[west, south], [east, south]], [[west, north], [east, north]]] })
  }
  return { type: 'FeatureCollection', features }
}

export type LegendRow = { ids: string[]; label: string; kind: CatalogLayer['kind']; layers: CatalogLayer[] }

/** Identical documented extents read as one row; each other layer keeps its own toggle. */
export function legendRows(layers: CatalogLayer[]): LegendRow[] {
  const rows: LegendRow[] = []
  const extents = layers.filter(layer => layer.kind === 'extent')
  for (const layer of layers) {
    if (layer.kind !== 'extent') rows.push({ ids: [layer.id], label: layer.label, kind: layer.kind, layers: [layer] })
    else if (layer === extents[0]) rows.push({ ids: extents.map(item => item.id), kind: 'extent', layers: extents,
      label: extents.length > 1 ? 'ERA5 · ERA5-Land extent' : layer.label })
  }
  return rows
}

export function catalogLayerSpecs(layer: CatalogLayer, id: string): AddLayerObject[] {
  const radius: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], 1, .8, 4, 1.6, 8, 3, 12, 4.5]
  const polygons: FilterSpecification = ['==', ['geometry-type'], 'Polygon']
  const points: FilterSpecification = ['==', ['geometry-type'], 'Point']
  // Area tints fade toward district zoom so they never hide the local map.
  const fade = (peak: number): ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 4, peak, 9, .04]
  if (layer.kind === 'stations') return [{ id: `${id}-point`, type: 'circle', source: id,
    paint: { 'circle-radius': radius, 'circle-color': MAP_PALETTE.OBSERVED, 'circle-opacity': .85 } }]
  if (layer.kind === 'sites') return [{ id: `${id}-point`, type: 'circle', source: id,
    paint: { 'circle-radius': radius, 'circle-color': MAP_PALETTE.PUBLISHED,
      'circle-opacity': ['case', ['get', 'approximate'], 0, .85],
      'circle-stroke-color': MAP_PALETTE.PUBLISHED_FAINT,
      'circle-stroke-width': ['case', ['get', 'approximate'], 1.2, 0] } }]
  if (layer.kind === 'cells') return [{ id: `${id}-fill`, type: 'fill', source: id, filter: polygons,
    paint: { 'fill-color': MAP_PALETTE.REGION, 'fill-antialias': false, 'fill-opacity': fade(.18) } }]
  if (layer.kind === 'area') return [
    { id: `${id}-fill`, type: 'fill', source: id, filter: polygons,
      paint: { 'fill-color': MAP_PALETTE.REGION, 'fill-opacity': fade(.07) } },
    { id: `${id}-line`, type: 'line', source: id, filter: polygons,
      paint: { 'line-color': MAP_PALETTE.REGION, 'line-width': .9, 'line-opacity': .85 } },
    { id: `${id}-point`, type: 'circle', source: id, filter: points,
      paint: { 'circle-radius': 4.5, 'circle-color': '#ffffff', 'circle-stroke-color': MAP_PALETTE.REGION,
        'circle-stroke-width': 1.6 } },
  ]
  return [{ id: `${id}-line`, type: 'line', source: id,
    paint: { 'line-color': MAP_PALETTE.EXTENT, 'line-width': 1, 'line-dasharray': [3, 3] } }]
}

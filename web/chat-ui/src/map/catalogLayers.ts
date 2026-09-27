import type { Feature, FeatureCollection, Geometry } from 'geojson'
import type { AddLayerObject, ExpressionSpecification, FilterSpecification } from 'maplibre-gl'
import type { CatalogLayer } from '../types'
import { SOURCE_COLORS, THEME } from '../theme'

/**
 * Map roles. The basemap and chrome are grey; weather-source layers carry the source colours,
 * separated by hue and shape. Amber belongs only to what the user chose.
 */
export const MAP_PALETTE = {
  HERO: THEME.AMBER,          // selected location, drawn/accepted geography
  HERO_LINE: THEME.AMBER_LINE,
  CANDIDATE: THEME.INK,       // geocoder candidate rings
  OBSERVED: SOURCE_COLORS.OBSERVED,   // NOAA station records: teal dots
  PUBLISHED: SOURCE_COLORS.PUBLISHED, // OneBuilding published files: deep-ocean squares
  PUBLISHED_FAINT: SOURCE_COLORS.PUBLISHED_FAINT,
  NSRDB: SOURCE_COLORS.NSRDB,         // NSRDB grid shade: orange
  REGION: SOURCE_COLORS.REGION,       // PVGIS outline
  EXTENT: SOURCE_COLORS.EXTENT,
} as const

type Swatch = { color: string; shape: 'dot' | 'square' | 'fill' | 'outline' | 'dash' }
const swatches: Record<CatalogLayer['kind'], Swatch> = {
  stations: { color: MAP_PALETTE.OBSERVED, shape: 'dot' },
  sites: { color: MAP_PALETTE.PUBLISHED, shape: 'square' },
  cells: { color: MAP_PALETTE.REGION, shape: 'fill' },
  area: { color: MAP_PALETTE.REGION, shape: 'outline' },
  extent: { color: MAP_PALETTE.EXTENT, shape: 'dash' },
}

// Station names are drawn by the map overlay (placeLabels) from this zoom.
export const STATION_LABEL_ZOOM = 7

export function layerSwatch(layer: Pick<CatalogLayer, 'id' | 'kind'>): Swatch {
  return layer.id === 'nsrdb' ? { ...swatches[layer.kind], color: MAP_PALETTE.NSRDB } : swatches[layer.kind]
}

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16)) as [number, number, number]
}

/** 12×12 px (drawn at pixel ratio 2) square markers, so OneBuilding differs from NOAA by shape too. */
function square(name: string, hex: string, hollow: boolean) {
  const size = 12
  const data = new Uint8Array(size * size * 4)
  const [r, g, b] = rgb(hex)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const edge = x < 2 || y < 2 || x >= size - 2 || y >= size - 2
    if (hollow && !edge) continue
    data.set([r, g, b, 235], (y * size + x) * 4)
  }
  return { name, width: size, height: size, data }
}

export const SHAPE_IMAGES = [square('oe-square', SOURCE_COLORS.PUBLISHED, false),
  square('oe-square-hollow', SOURCE_COLORS.PUBLISHED_FAINT, true)]

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
    for (const [lon, lat, id, ranges, name] of layer.points ?? []) {
      if (years.length && !reportsEveryYear(ranges as number[][], years)) continue
      feature({ type: 'Point', coordinates: [lon, lat] }, { id, name: name ?? '' })
    }
  } else if (layer.kind === 'sites') {
    for (const [lon, lat, label, period, position, name] of layer.points ?? []) {
      feature({ type: 'Point', coordinates: [lon, lat] }, { label, period, name: name ?? '',
        approximate: position !== 'published' && position !== 'consensus' })
    }
  } else if (layer.kind === 'cells') {
    for (const rect of layer.rects ?? []) feature(box(rect))
  } else if (layer.kind === 'area') {
    if (layer.polygon?.length) feature({ type: 'Polygon', coordinates: [layer.polygon] })
    for (const probe of layer.probes ?? []) feature({ type: 'Point', coordinates: probe }, { probe: true })
  } else if (layer.bounds) {
    // A documented extent carries its latitude limits as rims. ERA5-Land also gets a fill that
    // the map places beneath basemap water, so it reads as land cells only.
    const [west, south, east, north] = layer.bounds
    feature({ type: 'MultiLineString', coordinates: [[[west, south], [east, south]], [[west, north], [east, north]]] })
    if (layer.id === 'era5-land') feature(box(layer.bounds))
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
  if (layer.kind === 'sites') return [{ id: `${id}-point`, type: 'symbol', source: id,
    layout: { 'icon-image': ['case', ['get', 'approximate'], 'oe-square-hollow', 'oe-square'],
      'icon-size': ['interpolate', ['linear'], ['zoom'], 1, .3, 4, .5, 8, .8, 12, 1.1],
      'icon-allow-overlap': true, 'icon-ignore-placement': true } }]
  if (layer.kind === 'cells') return [{ id: `${id}-fill`, type: 'fill', source: id, filter: polygons,
    paint: { 'fill-color': layer.id === 'nsrdb' ? MAP_PALETTE.NSRDB : MAP_PALETTE.REGION,
      'fill-antialias': false, 'fill-opacity': fade(.22) } }]
  if (layer.kind === 'area') return [
    { id: `${id}-fill`, type: 'fill', source: id, filter: polygons,
      paint: { 'fill-color': MAP_PALETTE.REGION, 'fill-opacity': fade(.07) } },
    { id: `${id}-line`, type: 'line', source: id, filter: polygons,
      paint: { 'line-color': MAP_PALETTE.REGION, 'line-width': .9, 'line-opacity': .85 } },
    { id: `${id}-point`, type: 'circle', source: id, filter: points,
      paint: { 'circle-radius': 4.5, 'circle-color': THEME.PAPER, 'circle-stroke-color': MAP_PALETTE.REGION,
        'circle-stroke-width': 1.6 } },
  ]
  const rims: AddLayerObject = { id: `${id}-line`, type: 'line', source: id,
    filter: ['==', ['geometry-type'], 'LineString'],
    paint: { 'line-color': MAP_PALETTE.EXTENT, 'line-width': 1, 'line-dasharray': [3, 3] } }
  if (layer.id !== 'era5-land') return [rims]
  return [{ id: `${id}-fill`, type: 'fill', source: id, filter: polygons,
    metadata: { 'openepw:before': 'water' },
    paint: { 'fill-color': MAP_PALETTE.EXTENT, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 3, .28, 9, .1] } },
  rims]
}

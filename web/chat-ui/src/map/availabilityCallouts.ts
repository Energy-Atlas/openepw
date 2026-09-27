/** Screen layout for the product-availability tags shown while a weather product is chosen. */
import { SOURCE_COLORS, THEME } from '../theme'

export type ProductTag = {
  option: string; layer: string; tag: string; status: 'supported' | 'unknown'
  station?: { lat: number; lon: number; name?: string | null; distance_km?: number | null }
}
export type LocationAvailability = { index: number; lat: number; lon: number; name?: string | null; products: ProductTag[] }
export type ProductAvailability = {
  years: number[]; years_assumed: boolean; locations: LocationAvailability[]; omitted_locations: number
}
export type CalloutTag = {
  id: string; option: string; x: number; y: number; width: number; text: string
  color: string; textColor: string; status: ProductTag['status']
}
export type CalloutLine = { id: string; option: string[]; x1: number; y1: number; x2: number; y2: number; color: string }
type Point = { x: number; y: number }

export const TAG_HEIGHT = 17
const GAP = 3
const OFFSET = 12
const MARGIN = 40

/** Each tag takes the colour of the catalog layer that maps the product's coverage. */
export const TAG_COLORS: Record<string, string> = {
  noaa: SOURCE_COLORS.OBSERVED, onebuilding: SOURCE_COLORS.PUBLISHED, nsrdb: SOURCE_COLORS.NSRDB,
  pvgis: SOURCE_COLORS.REGION, era5: SOURCE_COLORS.EXTENT, 'era5-land': SOURCE_COLORS.EXTENT,
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
  return .2126 * r + .7152 * g + .0722 * b
}

/** Paper text where it reaches 4.5:1 on the tag colour, otherwise ink. */
export function tagTextColor(color: string): string {
  const contrast = (1.05) / (luminance(color) + .05)
  return contrast >= 4.5 ? THEME.PAPER : THEME.INK
}

function stack(products: ProductTag[], left: number, top: number, locationIndex: number, measure: (text: string) => number) {
  return products.map((product, i): CalloutTag => {
    const distance = product.station?.distance_km
    const text = `${product.tag}${distance != null ? ` · ${distance} km` : ''}${product.status === 'unknown' ? ' ?' : ''}`
    const color = TAG_COLORS[product.layer] ?? THEME.INK
    return { id: `${locationIndex}:${product.option}`, option: product.option, x: left, y: top + i * (TAG_HEIGHT + GAP),
      width: measure(text) + 16, text, color, textColor: tagTextColor(color), status: product.status }
  })
}

const stackHeight = (count: number) => count * TAG_HEIGHT + Math.max(0, count - 1) * GAP

/**
 * Grid products stack beside the location. A station product is looked up at a station, so
 * its tags sit by the line from the location to that station instead.
 */
export function layoutCallouts(locations: LocationAvailability[], project: (lon: number, lat: number) => Point,
  measure: (text: string) => number, size: { width: number; height: number }) {
  const tags: CalloutTag[] = []
  const lines: CalloutLine[] = []
  for (const location of locations) {
    const point = project(location.lon, location.lat)
    if (point.x < -MARGIN || point.y < -MARGIN || point.x > size.width + MARGIN || point.y > size.height + MARGIN) continue
    const grid = location.products.filter(product => !product.station)
    const gridTop = point.y - stackHeight(grid.length) / 2
    const gridTags = stack(grid, point.x + OFFSET, gridTop, location.index, measure)
    tags.push(...gridTags)
    type Box = { left: number; right: number; top: number; bottom: number }
    const boxes: Box[] = gridTags.length ? [{ left: point.x + OFFSET, top: gridTop, bottom: gridTop + stackHeight(grid.length),
      right: Math.max(...gridTags.map(tag => tag.x + tag.width)) }] : []
    // One line and one tag stack per looked-up station and layer.
    const groups = new Map<string, ProductTag[]>()
    for (const product of location.products.filter(product => product.station)) {
      const key = `${product.layer}:${product.station!.lat}:${product.station!.lon}`
      groups.set(key, [...(groups.get(key) ?? []), product])
    }
    for (const [key, products] of groups) {
      const station = project(products[0].station!.lon, products[0].station!.lat)
      const color = TAG_COLORS[products[0].layer] ?? THEME.INK
      lines.push({ id: `${location.index}:${key}`, option: products.map(product => product.option),
        x1: point.x, y1: point.y, x2: station.x, y2: station.y, color })
      const left = (point.x + station.x) / 2 + 8
      const placedFirst = stack(products, left, 0, location.index, measure)
      const width = Math.max(...placedFirst.map(tag => tag.width))
      const height = stackHeight(products.length)
      let top = (point.y + station.y) / 2 - height / 2
      // Keep each station stack off the grid stack and earlier station stacks.
      for (let moved = true; moved;) {
        moved = false
        for (const box of boxes)
          if (left < box.right + 4 && left + width > box.left - 4 && top < box.bottom + 4 && top + height > box.top - 4) {
            top = box.bottom + 6
            moved = true
          }
      }
      tags.push(...stack(products, left, top, location.index, measure))
      boxes.push({ left, right: left + width, top, bottom: top + height })
    }
  }
  return { tags, lines }
}

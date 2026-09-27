import { describe, expect, it } from 'vitest'
import { TAG_COLORS, TAG_HEIGHT, layoutCallouts, tagTextColor, type LocationAvailability } from '../src/map/availabilityCallouts'
import { SOURCE_COLORS, THEME } from '../src/theme'

// A flat test projection: one degree is 100 px, north up.
const project = (lon: number, lat: number) => ({ x: (lon + 77) * 100, y: (43 - lat) * 100 })
const measure = (text: string) => text.length * 6
const size = { width: 800, height: 600 }

const ithaca: LocationAvailability = { index: 0, lat: 42.444, lon: -76.5019, name: 'Ithaca', products: [
  { option: 'era5-openmeteo', layer: 'era5', tag: 'ERA5 · Open-Meteo', status: 'supported' },
  { option: 'nsrdb-actual', layer: 'nsrdb', tag: 'NSRDB actual year', status: 'unknown' },
  { option: 'noaa-isd', layer: 'noaa', tag: 'NOAA ISD', status: 'supported',
    station: { lat: 42.483, lon: -76.467, name: 'ITHACA TOMPKINS REGIONAL AIRPORT', distance_km: 5.2 } },
  { option: 'onebuilding:TMYx', layer: 'onebuilding', tag: 'TMYx', status: 'supported',
    station: { lat: 42.483, lon: -76.467, name: 'Ithaca Tompkins Rgnl AP', distance_km: 5.2 } },
  { option: 'onebuilding:TMYx.2009-2023', layer: 'onebuilding', tag: 'TMYx.2009-2023', status: 'supported',
    station: { lat: 42.483, lon: -76.467, name: 'Ithaca Tompkins Rgnl AP', distance_km: 5.2 } },
] }

describe('availability callouts', () => {
  it('stacks grid products left-aligned beside the location, one tag per product', () => {
    const { tags } = layoutCallouts([ithaca], project, measure, size)
    const point = project(ithaca.lon, ithaca.lat)
    const grid = tags.filter(tag => ['era5-openmeteo', 'nsrdb-actual'].includes(tag.option))
    expect(grid.map(tag => tag.x)).toEqual([point.x + 12, point.x + 12])        // left aligned
    expect(grid[1].y - grid[0].y).toBe(TAG_HEIGHT + 3)
    expect(grid.map(tag => tag.text)).toEqual(['ERA5 · Open-Meteo', 'NSRDB actual year ?'])
    expect(grid[1].status).toBe('unknown')
    expect(tags.filter(tag => tag.option.startsWith('onebuilding'))).toHaveLength(2)
  })

  it('draws one line per looked-up station and puts its tags by the line, not the location', () => {
    const { tags, lines } = layoutCallouts([ithaca], project, measure, size)
    const point = project(ithaca.lon, ithaca.lat)
    const station = project(-76.467, 42.483)
    expect(lines.map(line => [line.x1, line.y1, line.x2, line.y2])).toEqual([
      [point.x, point.y, station.x, station.y], [point.x, point.y, station.x, station.y]])  // from the location
    expect(lines.map(line => line.color)).toEqual([TAG_COLORS.noaa, TAG_COLORS.onebuilding])
    const noaa = tags.find(tag => tag.option === 'noaa-isd')!
    expect(noaa.text).toBe('NOAA ISD · 5.2 km')
    const grid = tags.filter(tag => tag.option === 'era5-openmeteo' || tag.option === 'nsrdb-actual')
    const gridBottom = Math.max(...grid.map(tag => tag.y + TAG_HEIGHT))
    for (const tag of tags.filter(tag => tag.option.startsWith('onebuilding') || tag.option === 'noaa-isd'))
      expect(tag.y >= gridBottom || tag.x > grid[0].x + grid[0].width).toBe(true)    // never on the grid stack
  })

  it('matches the catalog layer colours and keeps tag text readable', () => {
    expect(TAG_COLORS.noaa).toBe(SOURCE_COLORS.OBSERVED)
    expect(TAG_COLORS.nsrdb).toBe(SOURCE_COLORS.NSRDB)
    expect(tagTextColor(SOURCE_COLORS.OBSERVED)).toBe(THEME.PAPER)
    expect(tagTextColor(SOURCE_COLORS.NSRDB)).toBe(THEME.INK)
  })

  it('skips locations outside the view', () => {
    const away = { ...ithaca, lon: -60 }
    expect(layoutCallouts([away], project, measure, size).tags).toEqual([])
  })
})

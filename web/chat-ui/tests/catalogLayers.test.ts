import { describe, expect, it } from 'vitest'
import { catalogFeatures, reportsEveryYear } from '../src/map/catalogLayers'
import type { CatalogLayer } from '../src/types'
import { THEME } from '../src/theme'

const base = { caveat: '', evidence_dates: [], count: 0 }

describe('Stage 1 catalog layers', () => {
  it('keeps NOAA stations only when every requested year has reports', () => {
    const ranges = [[2010, 2012], [2016, 2018]]
    expect(reportsEveryYear(ranges, [2011, 2017])).toBe(true)
    expect(reportsEveryYear(ranges, [2012, 2013])).toBe(false)
    const layer: CatalogLayer = { ...base, id: 'noaa', kind: 'stations', label: 'NOAA',
      points: [[-76, 42, 'A', ranges], [10, 10, 'B', [[2000, 2001]]]] }
    expect(catalogFeatures(layer).features).toHaveLength(2)
    expect(catalogFeatures(layer, [2017]).features.map(feature => feature.properties?.id)).toEqual(['A'])
  })

  it('marks non-published OneBuilding positions as approximate', () => {
    const layer: CatalogLayer = { ...base, id: 'onebuilding', kind: 'sites', label: 'OB', points: [
      [1, 2, 'TMYx.2009-2023', '2009-2023', 'published'], [3, 4, 'TMY3', null, 'approximate_locality']] }
    expect(catalogFeatures(layer).features.map(feature => feature.properties?.approximate)).toEqual([false, true])
  })

  it('draws cells and areas as polygons, probes as points and extents as latitude rims', () => {
    const cells = catalogFeatures({ ...base, id: 'nsrdb', kind: 'cells', label: 'N',
      rects: [[-155, 10, -154.25, 10.25]] })
    expect(cells.features[0].geometry).toEqual({ type: 'Polygon', coordinates: [[
      [-155, 10], [-154.25, 10], [-154.25, 10.25], [-155, 10.25], [-155, 10]]] })
    const area = catalogFeatures({ ...base, id: 'pvgis', kind: 'area', label: 'P',
      polygon: [[0, 0], [1, 0], [1, 1], [0, 0]], probes: [[-0.128, 51.507]] })
    expect(area.features.map(feature => feature.geometry.type)).toEqual(['Polygon', 'Point'])
    const extent = catalogFeatures({ ...base, id: 'era5', kind: 'extent', label: 'E', bounds: [-180, -89, 180, 89] })
    expect(extent.features[0].geometry.type).toBe('MultiLineString')
  })
})

describe('OpenEPW map palette', () => {
  const layer = (id: string, kind: CatalogLayer['kind']): CatalogLayer => ({ ...base, id, kind, label: id })

  it('keeps amber for the user selection and gives catalog layers only palette roles', async () => {
    const { MAP_PALETTE, catalogLayerSpecs } = await import('../src/map/catalogLayers')
    const colors = [layer('noaa', 'stations'), layer('onebuilding', 'sites'), layer('nsrdb', 'cells'),
      layer('pvgis', 'area'), layer('era5', 'extent')]
      .flatMap(item => catalogLayerSpecs(item, `x-${item.id}`))
      .flatMap(spec => Object.entries((spec as { paint?: Record<string, unknown> }).paint ?? {})
        .filter(([key]) => key.endsWith('color')).map(([, value]) => JSON.stringify(value)))
    expect(colors.join()).not.toContain(MAP_PALETTE.HERO)
    const allowed = [MAP_PALETTE.OBSERVED, MAP_PALETTE.PUBLISHED, MAP_PALETTE.PUBLISHED_FAINT,
      MAP_PALETTE.REGION, MAP_PALETTE.EXTENT, MAP_PALETTE.NSRDB, THEME.PAPER]
    for (const value of colors) expect(allowed.some(color => value.includes(color))).toBe(true)
  })

  it('draws documented extents as a dashed rim without fill', async () => {
    const { catalogLayerSpecs } = await import('../src/map/catalogLayers')
    const specs = catalogLayerSpecs(layer('era5', 'extent'), 'x')
    expect(specs.map(spec => spec.type)).toEqual(['line'])
  })

  it('merges identical documented extents into one legend row', async () => {
    const { legendRows } = await import('../src/map/catalogLayers')
    const rows = legendRows([layer('noaa', 'stations'), { ...layer('era5', 'extent'), label: 'ERA5 global reanalysis' },
      { ...layer('era5-land', 'extent'), label: 'ERA5-Land reanalysis' }])
    expect(rows.map(row => row.ids)).toEqual([['noaa'], ['era5', 'era5-land']])
    expect(rows[1].label).toBe('ERA5 · ERA5-Land extent')
  })

  it('gives NSRDB its own orange and OneBuilding a square symbol', async () => {
    const { MAP_PALETTE, catalogLayerSpecs, SHAPE_IMAGES, layerSwatch } = await import('../src/map/catalogLayers')
    const cells = catalogLayerSpecs(layer('nsrdb', 'cells'), 'x')[0] as { paint: Record<string, unknown> }
    expect(cells.paint['fill-pattern']).toBe('oe-hatch-nsrdb')
    expect(MAP_PALETTE.NSRDB).not.toBe(MAP_PALETTE.HERO)
    const sites = catalogLayerSpecs(layer('onebuilding', 'sites'), 'y')[0] as { type: string; layout: Record<string, unknown> }
    expect(sites.type).toBe('symbol')
    expect(JSON.stringify(sites.layout['icon-image'])).toContain('oe-square')
    expect(SHAPE_IMAGES.map(image => image.name)).toEqual(['oe-square', 'oe-square-hollow'])
    expect(layerSwatch(layer('onebuilding', 'sites')).shape).toBe('square')
    expect(layerSwatch(layer('nsrdb', 'cells')).color).toBe(MAP_PALETTE.NSRDB)
  })

  it('shows the ERA5-Land extent as a land-only fill beneath basemap water', async () => {
    const { catalogFeatures, catalogLayerSpecs } = await import('../src/map/catalogLayers')
    const land = { ...layer('era5-land', 'extent'), bounds: [-180, -89, 180, 89] as [number, number, number, number] }
    const specs = catalogLayerSpecs(land, 'x') as Array<{ type: string; metadata?: Record<string, unknown> }>
    const fill = specs.find(spec => spec.type === 'fill')
    expect(fill?.metadata?.['openepw:before']).toBe('water')
    expect(catalogFeatures(land).features.map(feature => feature.geometry.type)).toEqual(['MultiLineString', 'Polygon'])
    expect(catalogLayerSpecs(layer('era5', 'extent'), 'y').map(spec => spec.type)).toEqual(['line'])
  })

  it('carries station names for the label overlay from zoom 8.5', async () => {
    const { catalogFeatures, catalogLayerSpecs, STATION_LABEL_ZOOM } = await import('../src/map/catalogLayers')
    const noaa: CatalogLayer = { ...base, id: 'noaa', kind: 'stations', label: 'N',
      points: [[-71, 42, 'A', [[2018, 2018]], 'BOSTON LOGAN INTL']] }
    const ob: CatalogLayer = { ...base, id: 'onebuilding', kind: 'sites', label: 'O',
      points: [[1, 2, 'TMYx', null, 'published', 'Coconut Island AP']] }
    expect(STATION_LABEL_ZOOM).toBe(8.5)
    expect(catalogFeatures(noaa).features[0].properties?.name).toBe('BOSTON LOGAN INTL')
    expect(catalogFeatures(ob).features[0].properties?.name).toBe('Coconut Island AP')
    // Names are drawn by the overlay (pills and callouts), not by MapLibre symbol layers.
    expect(catalogLayerSpecs(noaa, 'x').some(spec => spec.id === 'x-label')).toBe(false)
  })

  it('hatches every polygon layer in its own colour and direction', async () => {
    const { catalogLayerSpecs, HATCH_IMAGES, MAP_PALETTE } = await import('../src/map/catalogLayers')
    const land = { ...layer('era5-land', 'extent'), bounds: [-180, -89, 180, 89] as [number, number, number, number] }
    const fills = [layer('nsrdb', 'cells'), layer('pvgis', 'area'), land]
      .flatMap(item => catalogLayerSpecs(item, `x-${item.id}`))
      .filter(spec => spec.type === 'fill') as Array<{ paint: Record<string, unknown> }>
    expect(fills.map(spec => spec.paint['fill-pattern'])).toEqual(['oe-hatch-nsrdb', 'oe-hatch-region', 'oe-hatch-land'])
    expect(fills.every(spec => !('fill-color' in spec.paint))).toBe(true)
    const images = Object.fromEntries(HATCH_IMAGES.map(image => [image.name, image]))
    expect(Object.keys(images)).toEqual(['oe-hatch-nsrdb', 'oe-hatch-region', 'oe-hatch-land', 'oe-hatch-selection'])
    const nsrdb = images['oe-hatch-nsrdb']
    const alphas = [...Array(nsrdb.width * nsrdb.height).keys()].map(index => nsrdb.data[index * 4 + 3])
    expect(alphas.some(alpha => alpha === 0) && alphas.some(alpha => alpha > 0)).toBe(true)   // lines and gaps
    const inked = [...Array(nsrdb.width * nsrdb.height).keys()].find(index => nsrdb.data[index * 4 + 3] > 0)!
    expect([...nsrdb.data.slice(inked * 4, inked * 4 + 3)]).toEqual([0xf0, 0x7c, 0x2e])       // NSRDB orange
    const pixels = (name: string) => [...images[name].data].join()
    expect(new Set(HATCH_IMAGES.map(image => pixels(image.name))).size).toBe(4)               // distinct patterns
    expect(MAP_PALETTE.NSRDB).toBe('#f07c2e')
    expect(images['oe-hatch-land'].width).toBeLessThan(images['oe-hatch-nsrdb'].width)       // a finer ERA5 hatch
  })

  it('shows the ERA5-Land hatch in the legend swatch', async () => {
    const { layerSwatch } = await import('../src/map/catalogLayers')
    expect(layerSwatch(layer('era5-land', 'extent')).shape).toBe('lines')
    expect(layerSwatch(layer('era5', 'extent')).shape).toBe('dash')
  })
})

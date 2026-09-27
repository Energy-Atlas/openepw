import { describe, expect, it } from 'vitest'
import { catalogFeatures, layerColor, reportsEveryYear } from '../src/map/catalogLayers'
import type { CatalogLayer } from '../src/types'

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

  it('draws cells, areas with probes and extents as polygons', () => {
    const cells = catalogFeatures({ ...base, id: 'nsrdb', kind: 'cells', label: 'N',
      rects: [[-155, 10, -154.25, 10.25]] })
    expect(cells.features[0].geometry).toEqual({ type: 'Polygon', coordinates: [[
      [-155, 10], [-154.25, 10], [-154.25, 10.25], [-155, 10.25], [-155, 10]]] })
    const area = catalogFeatures({ ...base, id: 'pvgis', kind: 'area', label: 'P',
      polygon: [[0, 0], [1, 0], [1, 1], [0, 0]], probes: [[-0.128, 51.507]] })
    expect(area.features.map(feature => feature.geometry.type)).toEqual(['Polygon', 'Point'])
    const extent = catalogFeatures({ ...base, id: 'era5', kind: 'extent', label: 'E', bounds: [-180, -89, 180, 89] })
    expect(extent.features[0].geometry.type).toBe('Polygon')
    expect(layerColor('noaa')).not.toBe(layerColor('onebuilding'))
  })
})

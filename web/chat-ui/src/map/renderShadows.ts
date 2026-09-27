import type { Map as MapLibreMap, GeoJSONSource } from 'maplibre-gl'
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson'
import { projectShadowRing, roofShadow, terrainOccluded,
  type BuildingShape, type Coordinate } from './shadows'
import type { SceneSettings } from './scene'
import { solarPosition } from './sun'
import { THEME } from '../theme'

type Building = BuildingShape & { id: string }
const empty: FeatureCollection = { type: 'FeatureCollection', features: [] }
const maxBuildings = 120

function polygonFeature(rings: Coordinate[][], kind: string, height = 0): Feature<Polygon> {
  return { type: 'Feature', geometry: { type: 'Polygon', coordinates: rings },
    properties: { kind, height } }
}

function coordinates(feature: GeoJSON.Feature): Coordinate[][] {
  const geometry = feature.geometry
  if (geometry?.type === 'Polygon') return [geometry.coordinates[0] as Coordinate[]]
  if (geometry?.type === 'MultiPolygon') return geometry.coordinates.map(polygon => polygon[0] as Coordinate[])
  return []
}

function buildings(map: MapLibreMap): Building[] {
  if (!map.getSource('openmaptiles')) return []
  const result: Building[] = []
  const seen = new Set<string>()
  const canvas = map.getCanvas()
  const targetX = Math.max(0, canvas.clientWidth - 400) / 2
  const targetY = canvas.clientHeight / 2
  for (const feature of map.querySourceFeatures('openmaptiles', { sourceLayer: 'building' })) {
    const height = Number(feature.properties?.render_height ?? 5)
    if (!Number.isFinite(height) || height <= 0 || height > 500) continue
    for (const ring of coordinates(feature as unknown as GeoJSON.Feature)) {
      if (ring.length < 4 || ring.length > 100) continue
      const id = String(feature.id ?? ring.slice(0, 2).flat().join(','))
      if (seen.has(id)) continue
      const point = map.project(ring[0])
      if (point.x < -100 || point.y < -100 || point.x > canvas.clientWidth + 100
        || point.y > canvas.clientHeight + 100) continue
      seen.add(id)
      const ground = map.getTerrain() ? map.queryTerrainElevation(ring[0]) ?? 0 : 0
      result.push({ id, ring, height, ground })
      if (result.length >= 1000) break
    }
  }
  return result.sort((a, b) => {
    const pa = map.project(a.ring[0]), pb = map.project(b.ring[0])
    return (pa.x - targetX) ** 2 + (pa.y - targetY) ** 2
      - (pb.x - targetX) ** 2 - (pb.y - targetY) ** 2
  }).slice(0, maxBuildings)
}

function overlaps(a: Coordinate[], b: Coordinate[]): boolean {
  const bounds = (ring: Coordinate[]) => [Math.min(...ring.map(p => p[0])),
    Math.min(...ring.map(p => p[1])), Math.max(...ring.map(p => p[0])),
    Math.max(...ring.map(p => p[1]))]
  const x = bounds(a), y = bounds(b)
  return x[0] <= y[2] && x[2] >= y[0] && x[1] <= y[3] && x[3] >= y[1]
}

function projectedGroundRing(map: MapLibreMap, source: Building,
  sun: { elevationDeg: number; azimuthDeg: number }): Coordinate[] | null {
  if (!map.getTerrain()) return projectShadowRing(source.ring, source.height, sun)
  const tangent = Math.tan(sun.elevationDeg * Math.PI / 180)
  const azimuth = sun.azimuthDeg * Math.PI / 180
  if (tangent <= 0) return null
  return source.ring.map(([lon, lat]) => {
    const roof = source.height + (map.queryTerrainElevation([lon, lat]) ?? source.ground ?? 0)
    let targetGround = map.queryTerrainElevation([lon, lat]) ?? source.ground ?? 0
    let endpoint: Coordinate = [lon, lat]
    for (let iteration = 0; iteration < 3; iteration++) {
      const distance = Math.max(0, Math.min(2000, (roof - targetGround) / tangent))
      endpoint = [lon - Math.sin(azimuth) * distance /
        (111_320 * Math.max(0.1, Math.cos(lat * Math.PI / 180))),
      lat - Math.cos(azimuth) * distance / 111_320]
      targetGround = map.queryTerrainElevation(endpoint) ?? targetGround
    }
    return endpoint
  })
}

function terrainShadowCells(map: MapLibreMap, sun: { elevationDeg: number; azimuthDeg: number }): Feature<Polygon>[] {
  if (!map.getTerrain()) return []
  const bounds = map.getBounds()
  const center = map.getCenter()
  const lonScale = 111_320 * Math.cos(center.lat * Math.PI / 180)
  const latScale = 111_320
  const west = (bounds.getWest() - center.lng) * lonScale
  const east = (bounds.getEast() - center.lng) * lonScale
  const south = (bounds.getSouth() - center.lat) * latScale
  const north = (bounds.getNorth() - center.lat) * latScale
  // Bound DEM ray work even when the current district spans several kilometres.
  const step = Math.max(12, (east - west) / 24, (north - south) / 20)
  const sampled = (x: number, y: number) => map.queryTerrainElevation([
    center.lng + x / lonScale, center.lat + y / latScale])
  const result: Feature<Polygon>[] = []
  for (let x = west; x < east; x += step) {
    for (let y = south; y < north; y += step) {
      if (result.length >= 600) return result
      if (!terrainOccluded(x, y, sampled, sun, 240, 12)) continue
      const ring: Coordinate[] = [
        [x, y], [x + step, y], [x + step, y + step], [x, y + step], [x, y],
      ].map(([px, py]) => [center.lng + px / lonScale, center.lat + py / latScale])
      result.push(polygonFeature([ring], 'relief'))
    }
  }
  return result
}

function put(map: MapLibreMap, id: string, collection: FeatureCollection, layer: 'ground' | 'roof') {
  if (!map.getSource(id)) {
    map.addSource(id, { type: 'geojson', data: collection })
    const label = map.getStyle().layers?.find(item => item.type === 'symbol')?.id
    if (layer === 'ground') {
      map.addLayer({ id, type: 'fill', source: id,
        paint: { 'fill-color': THEME.INK,
          'fill-opacity': 0.28 } }, map.getLayer('openepw-buildings') ? 'openepw-buildings' : label)
    } else {
      map.addLayer({ id, type: 'fill-extrusion', source: id,
        paint: { 'fill-extrusion-color': THEME.INK, 'fill-extrusion-opacity': 0.35,
          'fill-extrusion-base': ['get', 'height'],
          'fill-extrusion-height': ['+', ['get', 'height'], 0.15] } }, label)
    }
  } else {
    (map.getSource(id) as GeoJSONSource).setData(collection)
  }
}

export function renderShadows(map: MapLibreMap, settings: SceneSettings): string {
  // Tiles may still be loading; sourcedata events re-run this as buildings arrive.
  if (!map.getStyle()) return 'Shadows waiting for map style.'
  if (!settings.view3d || !settings.shadows || map.getZoom() < 14) {
    for (const id of ['openepw-ground-shadows', 'openepw-roof-shadows']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none')
    }
    return !settings.view3d ? 'Shadows paused in flat view.' : !settings.shadows
      ? 'Cast shadows switched off.' : 'Zoom closer for district shadows.'
  }
  const center = map.getCenter()
  const sun = solarPosition(settings.dayOfYear, settings.utcMinutes, center.lat, center.lng)
  if (sun.elevationDeg <= 0) {
    put(map, 'openepw-ground-shadows', empty, 'ground')
    put(map, 'openepw-roof-shadows', empty, 'roof')
    return 'Sun below the local horizon; no direct cast shadows.'
  }
  if (map.getTerrain() && map.queryTerrainElevation([center.lng, center.lat]) === null) {
    for (const id of ['openepw-ground-shadows', 'openepw-roof-shadows']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none')
    }
    return 'Waiting for terrain elevation; cast shadows paused.'
  }
  const sources = buildings(map)
  const firstLabel = map.getStyle().layers?.find(item => item.type === 'symbol')?.id
  if (firstLabel && map.getLayer('openepw-buildings')) {
    map.moveLayer('openepw-buildings', firstLabel)
  }
  const ground: Feature<Polygon>[] = []
  const roofs: Feature<Polygon>[] = []
  for (const source of sources) {
    const projected = projectedGroundRing(map, source, sun)
    if (!projected) continue
    ground.push(polygonFeature([projected], 'building'))
    for (let i = 0; i < source.ring.length - 1; i++) {
      ground.push(polygonFeature([[
        source.ring[i], source.ring[i + 1], projected[i + 1], projected[i], source.ring[i],
      ]], 'building'))
    }
    for (const target of sources) {
      if (source.id === target.id || source.height + (source.ground ?? 0) <=
        target.height + (target.ground ?? 0) || !overlaps(projected, target.ring)) continue
      for (const shade of roofShadow(source, target, sun)) {
        roofs.push(polygonFeature(shade.rings, 'roof', shade.height))
      }
    }
  }
  ground.push(...terrainShadowCells(map, sun))
  const groundCollection: FeatureCollection<Polygon | MultiPolygon> = {
    type: 'FeatureCollection', features: ground,
  }
  put(map, 'openepw-ground-shadows', groundCollection, 'ground')
  put(map, 'openepw-roof-shadows', { type: 'FeatureCollection', features: roofs }, 'roof')
  for (const id of ['openepw-ground-shadows', 'openepw-roof-shadows']) {
    map.setLayoutProperty(id, 'visibility', 'visible')
  }
  if (sources.length) return `${sources.length} decorative buildings sampled; geometric shadows approximate.`
  return map.areTilesLoaded() ? 'Building geometry unavailable at this location; terrain shadows may still appear.'
    : 'Loading district tiles for shadows.'
}

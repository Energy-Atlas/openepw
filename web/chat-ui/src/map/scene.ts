import type { Map as MapLibreMap, VisibilitySpecification } from 'maplibre-gl'
import { solarPosition } from './sun'

export type Appearance = 'light' | 'dark' | 'monochrome' | 'landform' | 'clean' | 'engineering'
export type SceneSettings = {
  appearance: Appearance
  view3d: boolean
  terrain: boolean
  terrainExaggeration: number
  dayOfYear: number
  utcMinutes: number
  lightIntensity: number
  diffusion: number
  haze: number
  shadows: boolean
}

const styleNames: Record<Appearance, string> = {
  light: 'positron',
  dark: 'dark',
  monochrome: 'liberty',
  landform: 'fiord',
  clean: 'bright',
  engineering: 'dark',
}
export const appearanceTokens: Record<Appearance, { background: string; water: string;
  road: string; building: string; accent: string }> = {
  light: { background: '#f3f7f7', water: '#bed8dd', road: '#ffffff', building: '#829aa0', accent: '#237e8b' },
  dark: { background: '#15313d', water: '#122d3b', road: '#566d75', building: '#718991', accent: '#59b9c1' },
  monochrome: { background: '#ecefee', water: '#c9d0d0', road: '#fcfdfb', building: '#7e898a', accent: '#576d70' },
  landform: { background: '#e4e9e1', water: '#8fb6c2', road: '#e5e9dc', building: '#869780', accent: '#b27831' },
  clean: { background: '#f5f6f2', water: '#b2d7e1', road: '#ffffff', building: '#90a6a9', accent: '#1e8294' },
  engineering: { background: '#0b222d', water: '#092d3a', road: '#527078', building: '#5d838b', accent: '#d69b36' },
}
const hiddenBuildingLayers = new WeakMap<MapLibreMap, Map<string, VisibilitySpecification | undefined>>()

export function appearanceStyle(appearance: Appearance): string {
  return `https://tiles.openfreemap.org/styles/${styleNames[appearance]}`
}

export function scenePitch(settings: SceneSettings): number {
  return settings.view3d ? 50 : 0
}

export function applyAppearance(map: MapLibreMap, appearance: Appearance): void {
  const tokens = appearanceTokens[appearance]
  for (const layer of map.getStyle().layers ?? []) {
    if (layer.type === 'background') map.setPaintProperty(layer.id, 'background-color', tokens.background)
    if (/water/i.test(layer.id) && layer.type === 'fill') map.setPaintProperty(layer.id, 'fill-color', tokens.water)
    if ((appearance === 'engineering' || appearance === 'monochrome') && /road/i.test(layer.id)
      && layer.type === 'line') map.setPaintProperty(layer.id, 'line-color', tokens.road)
  }
}

export function applyLighting(map: MapLibreMap, settings: SceneSettings): void {
  if (!settings.view3d) return
  const center = map.getCenter()
  const sun = solarPosition(settings.dayOfYear, settings.utcMinutes, center.lat, center.lng)
  const daylight = Math.max(0, Math.min(1, (sun.elevationDeg + settings.diffusion / 12) / 15))
  const intensity = Math.min(0.9, settings.lightIntensity / 200) * daylight * (1 - settings.haze / 400)
  map.setLight({ anchor: 'map', position: [1.5, sun.azimuthDeg, Math.max(0, 90 - sun.elevationDeg)],
    color: '#eeddbb', intensity })
  map.setSky({ 'sky-color': daylight > 0 ? '#85b0bb' : '#122d42',
    'horizon-color': daylight > 0 ? '#dce4dc' : '#274253',
    'fog-color': '#c7d9d5', 'sky-horizon-blend': 0.35 + settings.diffusion / 500,
    'horizon-fog-blend': 0.4, 'fog-ground-blend': settings.haze / 200,
    'atmosphere-blend': 0.55 })
  if (map.getLayer('openepw-hillshade')) {
    map.setPaintProperty('openepw-hillshade', 'hillshade-illumination-direction', sun.azimuthDeg)
  }
}

export function applyScene(map: MapLibreMap, settings: SceneSettings): void {
  map.setProjection({ type: 'globe' })
  const hidden = hiddenBuildingLayers.get(map) ?? new Map<string, VisibilitySpecification | undefined>()
  hiddenBuildingLayers.set(map, hidden)
  for (const layer of map.getStyle().layers ?? []) {
    if (!('source-layer' in layer) || layer['source-layer'] !== 'building'
      || layer.id === 'openepw-buildings') continue
    if (settings.view3d) {
      if (!hidden.has(layer.id)) hidden.set(layer.id, layer.layout?.visibility)
      map.setLayoutProperty(layer.id, 'visibility', 'none')
    } else if (hidden.has(layer.id)) {
      map.setLayoutProperty(layer.id, 'visibility', hidden.get(layer.id) ?? 'visible')
      hidden.delete(layer.id)
    }
  }
  applyLighting(map, settings)
  if (settings.view3d && map.getSource('openmaptiles') && !map.getLayer('openepw-buildings')) {
    map.addLayer({
      id: 'openepw-buildings', type: 'fill-extrusion', source: 'openmaptiles',
      'source-layer': 'building', minzoom: 14,
      filter: ['!=', ['get', 'hide_3d'], true],
      paint: {
        'fill-extrusion-color': appearanceTokens[settings.appearance].building,
        'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 5],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': 0.82,
      },
    })
  }
  if (map.getLayer('openepw-buildings')) {
    map.setLayoutProperty('openepw-buildings', 'visibility', settings.view3d ? 'visible' : 'none')
    map.setPaintProperty('openepw-buildings', 'fill-extrusion-color',
      appearanceTokens[settings.appearance].building)
  }
  if (!settings.view3d || !settings.terrain) {
    map.setTerrain(null)
  } else {
    if (!map.getSource('openepw-terrain')) {
      map.addSource('openepw-terrain', {
        type: 'raster-dem',
        tiles: ['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'],
        tileSize: 512,
        maxzoom: 16,
        encoding: 'terrarium',
        attribution: '<a href="https://mapterhorn.com/attribution/">Mapterhorn terrain</a>',
      })
    }
    map.setTerrain({ source: 'openepw-terrain', exaggeration: settings.terrainExaggeration })
    if (!map.getSource('openepw-hillshade')) {
      map.addSource('openepw-hillshade', {
        type: 'raster-dem', tiles: ['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'],
        tileSize: 512, maxzoom: 16, encoding: 'terrarium',
        attribution: '<a href="https://mapterhorn.com/attribution/">Mapterhorn terrain</a>',
      })
    }
    if (!map.getLayer('openepw-hillshade')) {
      map.addLayer({ id: 'openepw-hillshade', type: 'hillshade', source: 'openepw-hillshade',
        paint: { 'hillshade-exaggeration': 0.35, 'hillshade-shadow-color': '#426675' } })
    }
  }
  if (map.getLayer('openepw-hillshade')) {
    map.setLayoutProperty('openepw-hillshade', 'visibility', settings.view3d && settings.terrain ? 'visible' : 'none')
  }
}

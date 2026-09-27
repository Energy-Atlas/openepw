import { useEffect, useRef, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { appearanceStyle, applyScene, scenePitch, type Appearance, type SceneSettings } from './scene'

const initial: SceneSettings = {
  appearance: 'light', view3d: false, terrain: false, terrainExaggeration: 1,
  dayOfYear: 172, utcMinutes: 960, lightIntensity: 100, diffusion: 25,
  haze: 20, shadows: true,
}

const appearances: Array<[Appearance, string]> = [
  ['light', 'Light'], ['dark', 'Dark'], ['monochrome', 'Technical monochrome'],
  ['landform', 'Landform'], ['clean', 'Clean technical'], ['engineering', 'Dark engineering'],
]

export function MapCanvas() {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const settingsRef = useRef(initial)
  const [settings, setSettings] = useState(initial)
  const [status, setStatus] = useState('Loading map')

  function change(patch: Partial<SceneSettings>) {
    setSettings(current => ({ ...current, ...patch }))
  }

  useEffect(() => {
    if (!host.current) return
    if (!window.WebGLRenderingContext) {
      setStatus('Interactive map requires WebGL. Use chat to enter coordinates or a place.')
      return
    }
    let cancelled = false
    let instance: MapLibreMap | null = null
    void import('maplibre-gl').then(maplibregl => {
      if (cancelled || !host.current) return
      maplibregl.setWorkerUrl(workerUrl)
      const sceneMap = new maplibregl.Map({
        container: host.current,
        style: appearanceStyle(settingsRef.current.appearance),
        center: [0, 18], zoom: 1.65,
        canvasContextAttributes: { antialias: true },
      })
      instance = sceneMap
      map.current = sceneMap
      sceneMap.on('style.load', () => {
        try { applyScene(sceneMap, settingsRef.current); sceneMap.jumpTo({ pitch: scenePitch(settingsRef.current) }); setStatus('Map ready') }
        catch { setStatus('Map scene unavailable; chat and coordinates remain usable.') }
      })
      sceneMap.on('error', () => setStatus('Some map tiles could not load. Chat remains available.'))
      sceneMap.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-left')
    }).catch(() => setStatus('Map unavailable. Use chat to enter coordinates or a place.'))
    return () => { cancelled = true; instance?.remove(); map.current = null }
  }, [])

  useEffect(() => {
    settingsRef.current = settings
    if (!map.current) return
    try { applyScene(map.current, settings) }
    catch { setStatus('Map scene unavailable; chat and coordinates remain usable.') }
  }, [settings])

  useEffect(() => { map.current?.easeTo({ pitch: scenePitch(settings), duration: 400 }) }, [settings.view3d])

  function setAppearance(appearance: Appearance) {
    change({ appearance })
    map.current?.setStyle(appearanceStyle(appearance))
  }

  return <div className="map-canvas" aria-label="Weather map">
    <div ref={host} className="map-engine" aria-hidden="true" />
    <div className="map-brand">OpenEPW <span>Weather across places and years</span></div>
    <section className="scene-controls" aria-label="Map scene controls">
      <button type="button" aria-pressed={settings.view3d} onClick={() => change({ view3d: !settings.view3d })}>3D view</button>
      <label><input type="checkbox" checked={settings.terrain} disabled={!settings.view3d}
        onChange={event => change({ terrain: event.target.checked })} /> Terrain</label>
      <label>Appearance <select value={settings.appearance} onChange={event => setAppearance(event.target.value as Appearance)}>
        {appearances.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
      </select></label>
      {settings.view3d && <details><summary>Sun and relief</summary>
        <label>Terrain scale <input type="range" min="1" max="10" value={settings.terrainExaggeration}
          disabled={!settings.terrain} onChange={event => change({ terrainExaggeration: Number(event.target.value) })} /> {settings.terrainExaggeration}×</label>
        <label>Day of year <input type="number" min="1" max="365" value={settings.dayOfYear}
          onChange={event => change({ dayOfYear: Number(event.target.value) })} /></label>
        <label>UTC time <input type="time" value={`${String(Math.floor(settings.utcMinutes / 60)).padStart(2, '0')}:${String(settings.utcMinutes % 60).padStart(2, '0')}`}
          onChange={event => { const [hours, minutes] = event.target.value.split(':').map(Number); change({ utcMinutes: hours * 60 + minutes }) }} /></label>
        <label><input type="checkbox" checked={settings.shadows} onChange={event => change({ shadows: event.target.checked })} /> Cast shadows</label>
        <p>Scene lighting and buildings are decorative; they do not change weather data or simulations.</p>
      </details>}
    </section>
    <div className="map-status" role="status">{status}</div>
  </div>
}

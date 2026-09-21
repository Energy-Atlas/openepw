import type { Appearance } from '../../shell/appearances'

/**
 * Stable color for a provider/dataset identity, shared by coverage overlays, point glyphs and
 * the map legend so one dataset never changes color between views.
 */
export function datasetColor(provider: string, dataset: string, appearance: Appearance) {
  const identity = `${provider}/${dataset}`
  const hash = [...identity].reduce(
    (value, character) => (value * 31 + character.charCodeAt(0)) | 0,
    0,
  )
  return appearance.data.categorical[Math.abs(hash) % appearance.data.categorical.length]
}

/** The first MapLibre layer id a coverage overlay adds, used as an insertion anchor. */
export function coverageAnchor(layer: { id: string; kind: string }) {
  return layer.kind === 'raster' ? `coverage-raster-${layer.id}` : `coverage-fill-${layer.id}`
}

/**
 * MapLibre draws later layers on top. The coverage list is ordered top-first, so each overlay is
 * inserted beneath the overlay listed above it.
 */
export function coverageBeforeIds(layers: { id: string; kind: string }[]) {
  return Object.fromEntries(
    layers.map((layer, index) => [
      layer.id,
      index === 0 ? undefined : coverageAnchor(layers[index - 1]),
    ]),
  ) as Record<string, string | undefined>
}

import type { FeatureCollection, Polygon } from 'geojson'
import type { AvailabilitySummary, CatalogScopes } from '../types'
import { THEME } from '../theme'

// Request-specific scopes stay in the neutral region role; amber belongs to the user's selection.
const colors: string[] = [THEME.SLATE]

/** Documentary source scopes; no feature represents verified point eligibility. */
export function availabilityFeatures(summary?: AvailabilitySummary | null,
  catalog?: CatalogScopes | null): FeatureCollection<Polygon> {
  const features: FeatureCollection<Polygon>['features'] = []
  const seen = new Set<string>()
  const layerColors = new Map<string, string>()
  const options = [...(catalog?.scopes ?? []), ...(summary?.options ?? [])]
  for (const option of options) {
    const bounds = option.footprint
    if (!bounds) continue
    const [west, south, east, north] = bounds
    if (![west, south, east, north].every(Number.isFinite) || west >= east || south >= north
      || south < -90 || north > 90) continue
    const convention = 'longitude_convention' in option ? option.longitude_convention : null
    let segments: Array<[number, number]>
    if (convention === '0_360' && west >= 0 && east <= 360) {
      segments = east - west >= 359.999 ? [[-180, 180]]
        : east <= 180 ? [[west, east]]
          : west >= 180 ? [[west - 360, east - 360]]
            : [[west, 180], [-180, east - 360]]
    } else if (west >= -180 && east <= 180) segments = [[west, east]]
    else continue
    const key = `${option.provider}/${option.dataset}`
    const identity = `${key}:${bounds.join(',')}`
    if (seen.has(identity)) continue
    seen.add(identity)
    if (!layerColors.has(key)) layerColors.set(key, colors[layerColors.size % colors.length])
    for (const [left, right] of segments) {
      features.push({ type: 'Feature', properties: { key, color: layerColors.get(key),
        basis: 'documented scope', checked_at: summary?.checked_at ?? catalog?.snapshot?.created_at },
      geometry: { type: 'Polygon', coordinates: [[
        [left, south], [right, south], [right, north], [left, north], [left, south],
      ]] } })
    }
  }
  return { type: 'FeatureCollection', features }
}

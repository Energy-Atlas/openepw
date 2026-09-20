import type { WeatherRequest } from './client'
export function validateDraft(value: unknown): asserts value is WeatherRequest {
  const fail = () => {
    throw Error(
      'Invalid request JSON structure. Use a point, point list, bounding box or GeoJSON Polygon; years/providers must be arrays.',
    )
  }
  const obj = (v: unknown): v is Record<string, unknown> =>
    typeof v === 'object' && v !== null && !Array.isArray(v)
  const finite = (v: unknown) => typeof v === 'number' && Number.isFinite(v)
  const point = (v: unknown) => obj(v) && finite(v.lat) && finite(v.lon)
  if (!obj(value)) return fail()
  const loc = value.locations
  const valid = Array.isArray(loc)
    ? loc.length > 0 && loc.every(point)
    : obj(loc) &&
      (point(loc) ||
        ['west', 'south', 'east', 'north'].every((k) => finite(loc[k])) ||
        (loc.type === 'Polygon' &&
          Array.isArray(loc.coordinates) &&
          loc.coordinates.length > 0 &&
          loc.coordinates.every(
            (r) =>
              Array.isArray(r) &&
              r.length >= 4 &&
              r.every((p) => Array.isArray(p) && p.length === 2 && p.every(finite)),
          )))
  if (!valid) return fail()
  if (value.years !== undefined && (!Array.isArray(value.years) || !value.years.every(finite)))
    return fail()
  if (
    value.providers !== undefined &&
    (!Array.isArray(value.providers) || !value.providers.every((p) => typeof p === 'string'))
  )
    return fail()
}

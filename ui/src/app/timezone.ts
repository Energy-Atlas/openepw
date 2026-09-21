/**
 * Longitude-based nominal standard time, matching openepw.models.nominal_offset_minutes:
 * whole hours of 15 degrees, halves rounding up. It keeps solar noon near 12:00 but can
 * differ from a site's legal standard time zone.
 */
export function nominalOffsetMinutes(lon: number) {
  return Math.floor(lon / 15 + 0.5) * 60
}

export function formatOffset(minutes: number) {
  if (minutes === 0) return 'UTC'
  const sign = minutes < 0 ? '−' : '+'
  const hours = Math.floor(Math.abs(minutes) / 60)
  const rest = Math.abs(minutes) % 60
  return `UTC${sign}${hours}${rest ? `:${String(rest).padStart(2, '0')}` : ''}`
}

/** An offset at least an hour from the longitude-based one shifts hours of day. */
export function offsetMismatch(minutes: number, lon: number) {
  return Math.abs(minutes - nominalOffsetMinutes(lon)) >= 60
}

/**
 * Moving a point keeps a deliberately chosen offset, but an offset that still equals the
 * old longitude's nominal value follows the point to its new longitude.
 */
export function followOffset<T extends { lon: number; standard_offset_minutes?: number }>(
  point: T,
  lon: number,
): T & { standard_offset_minutes: number } {
  const current = point.standard_offset_minutes ?? 0
  return {
    ...point,
    lon,
    standard_offset_minutes:
      current === nominalOffsetMinutes(point.lon) ? nominalOffsetMinutes(lon) : current,
  }
}

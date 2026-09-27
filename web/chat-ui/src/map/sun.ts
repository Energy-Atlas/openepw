export type SolarPosition = { elevationDeg: number; azimuthDeg: number }

/** One UTC instant drives the display scene, independent of browser timezone. */
export function utcSceneTime(date: Date): { dayOfYear: number; utcMinutes: number } {
  const start = Date.UTC(date.getUTCFullYear(), 0, 1)
  const currentDay = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
  return { dayOfYear: Math.round((currentDay - start) / 86_400_000) + 1,
    utcMinutes: date.getUTCHours() * 60 + date.getUTCMinutes() }
}

// NOAA fractional-year approximation for display lighting only.
export function solarPosition(dayOfYear: number, utcMinutes: number, lat: number, lon: number): SolarPosition {
  const rad = Math.PI / 180
  const gamma = 2 * Math.PI / 365 * (dayOfYear - 1 + (utcMinutes / 60 - 12) / 24)
  const equationMinutes = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma)
    - 0.032077 * Math.sin(gamma) - 0.014615 * Math.cos(2 * gamma)
    - 0.040849 * Math.sin(2 * gamma))
  const declination = 0.006918 - 0.399912 * Math.cos(gamma)
    + 0.070257 * Math.sin(gamma) - 0.006758 * Math.cos(2 * gamma)
    + 0.000907 * Math.sin(2 * gamma) - 0.002697 * Math.cos(3 * gamma)
    + 0.00148 * Math.sin(3 * gamma)
  const solarMinutes = ((utcMinutes + equationMinutes + 4 * lon) % 1440 + 1440) % 1440
  const hourAngle = (solarMinutes / 4 - 180) * rad
  const latitude = lat * rad
  const cosZenith = Math.sin(latitude) * Math.sin(declination)
    + Math.cos(latitude) * Math.cos(declination) * Math.cos(hourAngle)
  const zenith = Math.acos(Math.max(-1, Math.min(1, cosZenith)))
  const azimuth = Math.atan2(Math.sin(hourAngle),
    Math.cos(hourAngle) * Math.sin(latitude) - Math.tan(declination) * Math.cos(latitude)) / rad + 180
  return { elevationDeg: 90 - zenith / rad, azimuthDeg: (azimuth + 360) % 360 }
}

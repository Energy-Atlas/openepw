import { expect, it } from 'vitest'
import { calendarDay } from './WeatherCharts'

it('maps leap chronology according to the artifact calendar', () => {
  expect(calendarDay('2024-02-28T12:00:00', 'noleap')).toBe(59)
  expect(calendarDay('2024-03-01T12:00:00', 'noleap')).toBe(60)
  expect(calendarDay('2024-03-01T12:00:00', 'gregorian')).toBe(61)
})

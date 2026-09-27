import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { basemapPaint } from '../src/map/scene'
import { BASEMAP, THEME } from '../src/theme'

const allowed = new Set<string>([THEME.PAPER, THEME.INK, THEME.TEAL, THEME.AMBER, THEME.AMBER_LINE, THEME.SLATE,
  ...THEME.LADDER, ...THEME.RAMP].map(value => value.toLowerCase()))

describe('one OpenEPW colour system', () => {
  it('mirrors every theme token as a CSS variable', () => {
    const css = readFileSync('src/app.css', 'utf8')
    const vars = Object.fromEntries([...css.matchAll(/--(oe-[a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)]
      .map(([, name, value]) => [name, value.toLowerCase()]))
    expect(vars['oe-paper']).toBe(THEME.PAPER)
    expect(vars['oe-ink']).toBe(THEME.INK)
    expect(vars['oe-teal']).toBe(THEME.TEAL)
    expect(vars['oe-amber']).toBe(THEME.AMBER)
    expect(vars['oe-amber-line']).toBe(THEME.AMBER_LINE)
    expect(vars['oe-slate']).toBe(THEME.SLATE)
    THEME.LADDER.forEach((value, index) => expect(vars[`oe-l${index}`]).toBe(value))
  })

  it('uses no hex colour outside the theme anywhere in the stylesheet', () => {
    const css = readFileSync('src/app.css', 'utf8')
    const hexes = [...css.matchAll(/#[0-9a-f]{6}\b/gi)].map(([value]) => value.toLowerCase())
    expect(hexes.filter(value => !allowed.has(value) && value !== '#ffffff')).toEqual([])
  })

  it('recolours Positron roles from the theme', () => {
    const paint = (type: string, id: string, sourceLayer?: string) =>
      Object.fromEntries(basemapPaint({ type, id, 'source-layer': sourceLayer }))
    expect(paint('background', 'background')).toEqual({ 'background-color': BASEMAP.land })
    expect(paint('fill', 'water', 'water')).toEqual({ 'fill-color': BASEMAP.water })
    expect(paint('fill', 'park', 'park')).toEqual({ 'fill-color': BASEMAP.green })
    expect(paint('line', 'highway_major_casing', 'transportation')).toEqual({ 'line-color': BASEMAP.roadCasing })
    expect(paint('line', 'highway_minor', 'transportation')).toEqual({ 'line-color': BASEMAP.road })
    expect(paint('line', 'boundary_2', 'boundary')).toEqual({ 'line-color': BASEMAP.boundary })
    expect(paint('symbol', 'label_city', 'place')).toEqual({ 'text-color': BASEMAP.label, 'text-halo-color': BASEMAP.halo })
    expect(paint('symbol', 'water_name_point_label', 'water_name'))
      .toEqual({ 'text-color': BASEMAP.labelMinor, 'text-halo-color': BASEMAP.halo })
    for (const value of Object.values(BASEMAP)) expect(allowed.has(value.toLowerCase())).toBe(true)
  })
})

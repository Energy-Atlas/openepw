import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { basemapPaint } from '../src/map/scene'
import { BASEMAP, SERIES, SOURCE_COLORS, THEME } from '../src/theme'
import { MAP_PALETTE } from '../src/map/catalogLayers'

// One hue: paper, ink and the ladder mixed between them. Amber is the only other colour.
const mono = new Set<string>([THEME.PAPER, THEME.INK, THEME.BACKDROP, ...THEME.LADDER].map(value => value.toLowerCase()))
const allowed = new Set<string>([...mono, THEME.AMBER, THEME.AMBER_LINE, THEME.YES])

describe('one OpenEPW colour system', () => {
  it('mirrors every theme token as a CSS variable', () => {
    const css = readFileSync('src/app.css', 'utf8')
    const vars = Object.fromEntries([...css.matchAll(/--(oe-[a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)]
      .map(([, name, value]) => [name, value.toLowerCase()]))
    expect(vars['oe-paper']).toBe(THEME.PAPER)
    expect(vars['oe-ink']).toBe(THEME.INK)
    expect(vars['oe-amber']).toBe(THEME.AMBER)
    expect(vars['oe-amber-line']).toBe(THEME.AMBER_LINE)
    expect(vars['oe-yes']).toBe(THEME.YES)                                   // availability "yes" green
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

  it('keeps basemap, charts, chat and backdrop grey while weather sources carry colour', () => {
    const inMono = (value: string) => mono.has(value.toLowerCase())
    expect([...THEME.RAMP, ...SERIES, ...Object.values(BASEMAP)].every(inMono)).toBe(true)
    const { HERO, HERO_LINE, CANDIDATE, ...sources } = MAP_PALETTE
    expect([HERO, HERO_LINE]).toEqual([THEME.AMBER, THEME.AMBER_LINE])
    expect(inMono(CANDIDATE)).toBe(true)
    const sourceHues = new Set(Object.values(SOURCE_COLORS).map(value => value.toLowerCase()))
    for (const value of Object.values(sources)) expect(sourceHues.has(value.toLowerCase()) || inMono(value)).toBe(true)
    expect(new Set([MAP_PALETTE.OBSERVED, MAP_PALETTE.PUBLISHED, MAP_PALETTE.REGION]).size).toBe(3)
    expect([MAP_PALETTE.OBSERVED, MAP_PALETTE.PUBLISHED, MAP_PALETTE.REGION].some(inMono)).toBe(false)
    const css = readFileSync('src/app.css', 'utf8')
    for (const value of sourceHues) expect(css.toLowerCase()).not.toContain(value)
  })

  it('is true greyscale with a dark grey backdrop', () => {
    const grey = (value: string) => value[1] + value[2] === value[3] + value[4] && value[3] + value[4] === value[5] + value[6]
    expect([...mono].every(grey)).toBe(true)
    expect(BASEMAP.space).toBe(THEME.BACKDROP)
    const css = readFileSync('src/app.css', 'utf8')
    expect(css).toMatch(/--oe-backdrop:\s*#333333/)
    expect(css).toMatch(/\.map-canvas \{[^}]*background: var\(--oe-backdrop\)/)
  })

  it('uses Geist everywhere except monospace', () => {
    const css = readFileSync('src/app.css', 'utf8')
    expect(css).toMatch(/family=Geist/)
    expect(css).toMatch(/:root \{[^}]*font-family: 'Geist'/)
    expect(css).not.toContain('IBM Plex Sans')
  })
})

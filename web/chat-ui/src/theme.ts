/**
 * The single OpenEPW colour system for the whole browser UI: chat, legend, panels, charts,
 * catalog layers, basemap and backdrop. True greyscale by owner decision (2026-09-27):
 * neutral greys from paper to ink on a dark grey backdrop, separated by lightness and
 * shape. Solar amber is
 * the only other colour and marks the user's own selection. app.css mirrors these values
 * as CSS variables and a test keeps the two in sync.
 */
export const THEME = {
  PAPER: '#f2f2f2',           // light grey: page, bubbles, basemap roads
  INK: '#1f1f1f',             // near black: text, strong marks, actions
  BACKDROP: '#333333',        // dark grey: page and space around the globe
  AMBER: '#d69b36',           // the single accent: the user's own selection
  AMBER_LINE: '#9f762f',      // amber mixed 30% toward ink for 3:1 lines on paper
  // Paper→ink ladder (4, 8, 14, 22, 35, 55, 75%): land, water, rules, secondary marks, muted text.
  LADDER: ['#eaeaea', '#e1e1e1', '#d4d4d4', '#c4c4c4', '#a8a8a8', '#7e7e7e', '#545454'],
  // Ordinal ramp for value encodings: light to dark along the same ladder.
  RAMP: ['#e1e1e1', '#c4c4c4', '#7e7e7e', '#545454', '#1f1f1f'],
} as const

/**
 * Weather-source layers are the one place colour returns (owner decision 2026-09-27): the
 * plan's teal, deep ocean and slate on the grey basemap. Lighter variants mix toward paper.
 */
export const SOURCE_COLORS = {
  OBSERVED: '#237e8b',        // NOAA station records
  PUBLISHED: '#173849',       // OneBuilding published files
  PUBLISHED_FAINT: '#84959e', // approximate OneBuilding positions (50% toward paper)
  NSRDB: '#f07c2e',           // NSRDB source grid: bright orange, redder than the amber accent
  REGION: '#647782',          // PVGIS region
  EXTENT: '#88969e',          // ERA5 documented extent rims (25% toward paper)
} as const

export const MUTED_TEXT = THEME.LADDER[6]   // 6.8:1 on paper

/** Series colours by importance, darkest first; at most four, then use labels. */
export const SERIES = [THEME.INK, THEME.LADDER[5], THEME.LADDER[4], THEME.LADDER[3]] as const

/** Basemap roles derived from the theme; the only basemap appearance the UI uses. */
export const BASEMAP = {
  land: THEME.LADDER[0],
  green: THEME.LADDER[1],     // parks and landcover: texture, not a data hue
  water: THEME.LADDER[3],
  waterLine: THEME.LADDER[4],
  road: THEME.PAPER,
  roadMajor: THEME.PAPER,
  roadCasing: THEME.LADDER[2],
  boundary: THEME.LADDER[5],
  building: THEME.LADDER[2],
  buildingExtrusion: THEME.LADDER[4],
  label: THEME.INK,
  labelMinor: MUTED_TEXT,
  halo: THEME.PAPER,
  space: THEME.BACKDROP,
} as const

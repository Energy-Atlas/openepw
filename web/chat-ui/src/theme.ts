/**
 * The single OpenEPW colour system for the whole browser UI: chat, legend, panels, charts,
 * catalog layers, basemap and backdrop. Monochrome by owner decision (2026-09-27): one
 * deep-ocean hue from pale cloud to ink, separated by lightness and shape. Solar amber is
 * the only other colour and marks the user's own selection. app.css mirrors these values
 * as CSS variables and a test keeps the two in sync.
 */
export const THEME = {
  PAPER: '#f3f7f7',           // pale cloud: page, bubbles, basemap roads
  INK: '#173849',             // deep ocean: text, strong marks, actions, globe backdrop
  AMBER: '#d69b36',           // the single accent: the user's own selection
  AMBER_LINE: '#9d7d3c',      // amber mixed 30% toward ink for 3:1 lines on paper
  // Paper→ink ladder (4, 8, 14, 22, 35, 55, 75%): land, water, rules, secondary marks, muted text.
  LADDER: ['#eaeff0', '#e1e8e9', '#d4dcdf', '#c3cdd1', '#a6b4ba', '#7a8e97', '#4e6874'],
  // Ordinal ramp for value encodings: light to dark along the same ladder.
  RAMP: ['#e1e8e9', '#c3cdd1', '#7a8e97', '#4e6874', '#173849'],
} as const

export const MUTED_TEXT = THEME.LADDER[6]   // 5.5:1 on paper

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
  space: THEME.INK,
} as const

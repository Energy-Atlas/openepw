// Curated appearances (decision 0009, guidelines sections 4 to 6). Each one
// defines the chrome tokens written to CSS custom properties and the data
// palette read by canvas renderers (map, charts), so one definition drives
// every view. Contrast is checked in appearances.test.ts.

export type ColorScheme = 'light' | 'dark'

export const APPEARANCE_IDS = [
  'light',
  'dark',
  'monochrome',
  'lieflat',
  'cleanLight',
  'darkEngineering',
] as const

export type AppearanceId = (typeof APPEARANCE_IDS)[number]

/** "system" follows the operating system between Light and Dark. */
export type AppearancePreference = 'system' | AppearanceId

export type ChromeTokens = {
  bg: string
  surface: string
  surfaceRaised: string
  text: string
  textMuted: string
  border: string
  borderSubtle: string
  accent: string
  accentText: string
  onAccent: string
  focus: string
  selectedBg: string
  toneSuccessText: string
  toneSuccessBg: string
  toneInfoText: string
  toneInfoBg: string
  toneWarningText: string
  toneWarningBg: string
  toneDangerText: string
  toneDangerBg: string
  toneNeutralText: string
  toneNeutralBg: string
  shadowPopover: string
}

export const CHROME_VARIABLES: Record<keyof ChromeTokens, string> = {
  bg: '--color-bg',
  surface: '--color-surface',
  surfaceRaised: '--color-surface-raised',
  text: '--color-text',
  textMuted: '--color-text-muted',
  border: '--color-border',
  borderSubtle: '--color-border-subtle',
  accent: '--color-accent',
  accentText: '--color-accent-text',
  onAccent: '--color-on-accent',
  focus: '--color-focus',
  selectedBg: '--color-selected-bg',
  toneSuccessText: '--tone-success-text',
  toneSuccessBg: '--tone-success-bg',
  toneInfoText: '--tone-info-text',
  toneInfoBg: '--tone-info-bg',
  toneWarningText: '--tone-warning-text',
  toneWarningBg: '--tone-warning-bg',
  toneDangerText: '--tone-danger-text',
  toneDangerBg: '--tone-danger-bg',
  toneNeutralText: '--tone-neutral-text',
  toneNeutralBg: '--tone-neutral-bg',
  shadowPopover: '--shadow-popover',
}

export type DataPalette = {
  /** Categorical slots in fixed order; a color follows its entity, not its rank. */
  categorical: readonly [string, string, string]
  /** Recessive gray for reference series such as the baseline. */
  deemphasis: string
  /** Sequential ramp from low to high values. */
  sequential: readonly string[]
  noData: string
  /** Outline for selected map features. */
  selection: string
  networkLine: string
  networkPoint: string
  ink: {
    primary: string
    secondary: string
    muted: string
    grid: string
    axis: string
    surface: string
  }
  /**
   * Scene lighting for the map (decision 0019). The sky, horizon and light
   * colours are mixed from these by solar elevation, so each appearance lights
   * its own way and the monochrome themes stay monochrome.
   */
  sky: {
    /** Zenith in full day. */
    day: string
    /** Zenith in full night. */
    night: string
    /** The band around the horizon while the sun is near it. */
    twilight: string
    /** Warm cast of a low sun. */
    golden: string
    /** Haze and fog veil. */
    haze: string
    /** Directional light by day. */
    sunlight: string
    /** Directional light after dark. */
    moonlight: string
  }
  /** Reserved for state; always shown with an icon and a label. */
  status: { good: string; warning: string; critical: string }
}

export type Appearance = {
  id: AppearanceId
  label: string
  description: string
  scheme: ColorScheme
  chrome: ChromeTokens
  data: DataPalette
}

type ToneTokens = Pick<
  ChromeTokens,
  | 'toneSuccessText'
  | 'toneSuccessBg'
  | 'toneInfoText'
  | 'toneInfoBg'
  | 'toneWarningText'
  | 'toneWarningBg'
  | 'toneDangerText'
  | 'toneDangerBg'
  | 'toneNeutralText'
  | 'toneNeutralBg'
  | 'shadowPopover'
>

const LIGHT_TONES: ToneTokens = {
  toneSuccessText: '#1e6b37',
  toneSuccessBg: '#e6f4ea',
  toneInfoText: '#1d5fb8',
  toneInfoBg: '#e7f0fb',
  toneWarningText: '#7a4d00',
  toneWarningBg: '#fdf1dc',
  toneDangerText: '#a8231b',
  toneDangerBg: '#fbe9e7',
  toneNeutralText: '#3d4652',
  toneNeutralBg: '#eef1f4',
  shadowPopover: '0 8px 24px rgb(0 0 0 / 18%)',
}

const DARK_TONES: ToneTokens = {
  toneSuccessText: '#7fd69a',
  toneSuccessBg: '#16301f',
  toneInfoText: '#8cbcff',
  toneInfoBg: '#152a45',
  toneWarningText: '#f2c46b',
  toneWarningBg: '#3a2a0c',
  toneDangerText: '#ff9a8f',
  toneDangerBg: '#3d1714',
  toneNeutralText: '#c5ccd6',
  toneNeutralBg: '#262b32',
  shadowPopover: '0 8px 24px rgb(0 0 0 / 55%)',
}

const STATUS: DataPalette['status'] = {
  good: '#0ca30c',
  warning: '#fab219',
  critical: '#d03b3b',
}

export const APPEARANCES: Record<AppearanceId, Appearance> = {
  light: {
    id: 'light',
    label: 'Light',
    description:
      'The default light workbench: neutral chrome with blue, orange, and green data colors.',
    scheme: 'light',
    chrome: {
      bg: '#f5f6f8',
      surface: '#ffffff',
      surfaceRaised: '#eef1f4',
      text: '#1b1f24',
      textMuted: '#5b6573',
      border: '#d5dae1',
      borderSubtle: '#e6e9ed',
      accent: '#1f6fd1',
      accentText: '#1d5fb8',
      onAccent: '#ffffff',
      focus: '#1f6fd1',
      selectedBg: '#e3ecf8',
      ...LIGHT_TONES,
    },
    data: {
      categorical: ['#2a78d6', '#eb6834', '#15986a'],
      deemphasis: '#898781',
      sequential: ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'],
      noData: '#d5dae1',
      selection: '#1b1f24',
      networkLine: '#52514e',
      networkPoint: '#eb6834',
      ink: {
        primary: '#1b1f24',
        secondary: '#52514e',
        muted: '#5b6573',
        grid: '#e1e0d9',
        axis: '#c3c2b7',
        surface: '#ffffff',
      },
      sky: {
        day: '#86b6ef',
        night: '#0d1b2a',
        twilight: '#4a6b93',
        golden: '#eb6834',
        haze: '#93a4bb',
        sunlight: '#fff4e2',
        moonlight: '#3b4f6b',
      },
      status: STATUS,
    },
  },
  dark: {
    id: 'dark',
    label: 'Dark',
    description:
      'The default dark workbench with the same data colors adjusted for a dark surface.',
    scheme: 'dark',
    chrome: {
      bg: '#15181c',
      surface: '#1d2126',
      surfaceRaised: '#262b32',
      text: '#e6e9ed',
      textMuted: '#9aa4b1',
      border: '#343a42',
      borderSubtle: '#2a2f36',
      accent: '#5aa2ff',
      accentText: '#8cbcff',
      onAccent: '#0b1a2e',
      focus: '#5aa2ff',
      selectedBg: '#1c3350',
      ...DARK_TONES,
    },
    data: {
      categorical: ['#3987e5', '#d95926', '#199e70'],
      deemphasis: '#898781',
      // The anchor flips so values near zero recede toward the dark surface.
      sequential: ['#104281', '#1c5cab', '#2a78d6', '#6da7ec', '#cde2fb'],
      noData: '#3a3f47',
      selection: '#e6e9ed',
      networkLine: '#c3c2b7',
      networkPoint: '#d95926',
      ink: {
        primary: '#e6e9ed',
        secondary: '#c3c2b7',
        muted: '#9aa4b1',
        grid: '#2c2c2a',
        axis: '#383835',
        surface: '#1d2126',
      },
      sky: {
        day: '#3a6ea5',
        night: '#080b10',
        twilight: '#2b4260',
        golden: '#d95926',
        haze: '#2a323c',
        sunlight: '#f2e6d4',
        moonlight: '#2a3a52',
      },
      status: STATUS,
    },
  },
  monochrome: {
    id: 'monochrome',
    label: 'Technical monochrome',
    description:
      'A restrained neutral interface with gray data ink and orange and blue highlights.',
    scheme: 'light',
    chrome: {
      bg: '#f4f4f3',
      surface: '#ffffff',
      surfaceRaised: '#ededeb',
      text: '#1c1c1b',
      textMuted: '#5f5f5b',
      border: '#d6d6d2',
      borderSubtle: '#e8e8e5',
      accent: '#1c1c1b',
      accentText: '#1c1c1b',
      onAccent: '#ffffff',
      focus: '#1c1c1b',
      selectedBg: '#e8e8e5',
      ...LIGHT_TONES,
      toneInfoText: '#1c1c1b',
      toneInfoBg: '#ededeb',
      toneNeutralText: '#3d3d3a',
      toneNeutralBg: '#ededeb',
    },
    data: {
      categorical: ['#2f2f2d', '#c2410c', '#2563eb'],
      deemphasis: '#8c8c87',
      sequential: ['#e4e4e1', '#b8b8b3', '#8a8a85', '#5c5c58', '#2f2f2d'],
      noData: '#efdccb',
      selection: '#c2410c',
      networkLine: '#4a4a47',
      networkPoint: '#c2410c',
      ink: {
        primary: '#1c1c1b',
        secondary: '#4a4a47',
        muted: '#5f5f5b',
        grid: '#ebebe8',
        axis: '#cfcfcb',
        surface: '#ffffff',
      },
      sky: {
        day: '#c9c9c5',
        night: '#1c1c1b',
        twilight: '#6f6f6b',
        golden: '#c2410c',
        haze: '#a6a6a1',
        sunlight: '#ffffff',
        moonlight: '#4a4a47',
      },
      status: STATUS,
    },
  },
  lieflat: {
    id: 'lieflat',
    label: 'Lieflat-inspired',
    description:
      'A warmer analytical palette: paper tones, deep navy data ink, and a restrained terracotta accent.',
    scheme: 'light',
    chrome: {
      bg: '#f6f3ee',
      surface: '#fffdf9',
      surfaceRaised: '#efe9e0',
      text: '#1b2433',
      textMuted: '#5c6370',
      border: '#dcd4c7',
      borderSubtle: '#ebe5da',
      accent: '#1f3a5f',
      accentText: '#1f3a5f',
      onAccent: '#fffdf9',
      focus: '#1f3a5f',
      selectedBg: '#e4e8ee',
      ...LIGHT_TONES,
      toneInfoText: '#1f3a5f',
      toneInfoBg: '#e4e8ee',
      toneNeutralText: '#474d59',
      toneNeutralBg: '#efe9e0',
    },
    data: {
      categorical: ['#1f3a5f', '#c0503a', '#5d84ad'],
      deemphasis: '#968e80',
      sequential: ['#e3e8ef', '#b4c2d4', '#7f97b4', '#4a6a91', '#1f3a5f'],
      noData: '#e9dcc8',
      selection: '#c0503a',
      networkLine: '#4b5261',
      networkPoint: '#c0503a',
      ink: {
        primary: '#1b2433',
        secondary: '#4b5261',
        muted: '#5c6370',
        grid: '#ece6dc',
        axis: '#d3cabb',
        surface: '#fffdf9',
      },
      sky: {
        day: '#b4c2d4',
        night: '#141b26',
        twilight: '#4a6a91',
        golden: '#c0503a',
        haze: '#a99e8c',
        sunlight: '#fff6e8',
        moonlight: '#2f3f56',
      },
      status: STATUS,
    },
  },
  cleanLight: {
    id: 'cleanLight',
    label: 'Clean technical light',
    description:
      'A cool light interface with subdued gray chrome and a limited blue and cyan palette.',
    scheme: 'light',
    chrome: {
      bg: '#f3f5f7',
      surface: '#ffffff',
      surfaceRaised: '#ebeff3',
      text: '#16202a',
      textMuted: '#56626e',
      border: '#d6dde4',
      borderSubtle: '#e6ebf0',
      accent: '#0b67c2',
      accentText: '#0a5aa8',
      onAccent: '#ffffff',
      focus: '#0b67c2',
      selectedBg: '#e0edf9',
      ...LIGHT_TONES,
      toneInfoText: '#0a5aa8',
      toneInfoBg: '#e0edf9',
    },
    data: {
      categorical: ['#0b67c2', '#0f93b0', '#1c2f45'],
      deemphasis: '#87939f',
      sequential: ['#dcebf7', '#a9cdea', '#62a6d8', '#1f7cc0', '#0b4f86'],
      noData: '#e3dfd8',
      selection: '#16202a',
      networkLine: '#45515d',
      networkPoint: '#16202a',
      ink: {
        primary: '#16202a',
        secondary: '#45515d',
        muted: '#56626e',
        grid: '#e9edf1',
        axis: '#cdd4db',
        surface: '#ffffff',
      },
      sky: {
        day: '#a9cdea',
        night: '#0c1620',
        twilight: '#3f6d93',
        golden: '#c08a52',
        haze: '#9aa7b6',
        sunlight: '#fffaf0',
        moonlight: '#35506e',
      },
      status: STATUS,
    },
  },
  darkEngineering: {
    id: 'darkEngineering',
    label: 'Dark engineering',
    description:
      'A dark neutral theme with controlled, non-neon data colors and the same semantic colors as the light themes.',
    scheme: 'dark',
    chrome: {
      bg: '#121416',
      surface: '#1a1d21',
      surfaceRaised: '#23272c',
      text: '#e4e7eb',
      textMuted: '#9aa3ad',
      border: '#30353c',
      borderSubtle: '#262a30',
      accent: '#6aa3e0',
      accentText: '#8fb8e6',
      onAccent: '#0d1620',
      focus: '#8fb8e6',
      selectedBg: '#1f3147',
      ...DARK_TONES,
      toneInfoText: '#8fb8e6',
      toneInfoBg: '#1a2a3d',
    },
    data: {
      categorical: ['#6aa3e0', '#d9975b', '#5fb39a'],
      deemphasis: '#7b828a',
      sequential: ['#1d3148', '#2c4d6f', '#44719b', '#6d9cc8', '#a9c8e6'],
      noData: '#3a3f46',
      selection: '#f0f2f5',
      networkLine: '#b8bfc7',
      networkPoint: '#d9975b',
      ink: {
        primary: '#e4e7eb',
        secondary: '#b8bfc7',
        muted: '#9aa3ad',
        grid: '#262a30',
        axis: '#3a4048',
        surface: '#1a1d21',
      },
      sky: {
        day: '#44719b',
        night: '#0a0d10',
        twilight: '#2c4d6f',
        golden: '#d9975b',
        haze: '#262a30',
        sunlight: '#efe3d2',
        moonlight: '#25384f',
      },
      status: STATUS,
    },
  },
}

export const APPEARANCE_LIST: Appearance[] = APPEARANCE_IDS.map((id) => APPEARANCES[id])

export function isAppearanceId(value: string): value is AppearanceId {
  return (APPEARANCE_IDS as readonly string[]).includes(value)
}

export function resolveAppearance(
  preference: AppearancePreference,
  systemDark: boolean,
): Appearance {
  if (preference === 'system') {
    return systemDark ? APPEARANCES.dark : APPEARANCES.light
  }
  return APPEARANCES[preference]
}

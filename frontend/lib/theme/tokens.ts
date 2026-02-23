/**
 * Design tokens for the TeleClaude color system.
 *
 * NOTE: lib/theme/tokens.css is the visual source of truth for the frontend.
 * Edit that file to get color pickers and auto-completion.
 *
 * This file provides the logic-level access to hex values for non-CSS contexts:
 *   - Canvas animations (blending, interpolation)
 *   - CLI / Terminal rendering (Ink)
 */

// ---------------------------------------------------------------------------
// Type definitions
// ---------------------------------------------------------------------------

export type AgentType = 'claude' | 'gemini' | 'codex'
export type ThemeMode = 'dark' | 'light'
export type AgentColorLevel = 'subtle' | 'muted' | 'normal' | 'highlight'

export interface AgentPalette {
  readonly subtle: string
  readonly muted: string
  readonly normal: string
  readonly highlight: string
  /** Hex color for tmux pane background hazes. */
  readonly haze: string
}

export interface ThemeTokens {
  readonly bg: {
    readonly base: string
    readonly surface: string
    readonly elevated: string
    readonly overlay: string
  }
  readonly text: {
    readonly primary: string
    readonly secondary: string
    readonly muted: string
  }
  readonly border: {
    readonly default: string
    readonly subtle: string
    readonly modal: string
    readonly input: string
  }
  readonly selection: {
    readonly base: string
    readonly surface: string
    readonly elevated: string
  }
  readonly status: {
    readonly active: string
    readonly idle: string
    readonly error: string
    readonly ready: string
    readonly warning: string
  }
  readonly banner: string
  readonly tabLine: string
  readonly peaceful: {
    readonly normal: string
    readonly muted: string
  }
  readonly statusBarFg: string
}

// ---------------------------------------------------------------------------
// Agent color palettes (Synced with tokens.css)
// ---------------------------------------------------------------------------

const AGENT_COLORS_DARK = {
  claude: {
    subtle: '#875f00',
    muted: '#af875f',
    normal: '#d7af87',
    highlight: '#ffffff',
    haze: '#af875f',
  },
  gemini: {
    subtle: '#8787af',
    muted: '#af87ff',
    normal: '#d7afff',
    highlight: '#ffffff',
    haze: '#af87ff',
  },
  codex: {
    subtle: '#5f87af',
    muted: '#87afd7',
    normal: '#afd7ff',
    highlight: '#ffffff',
    haze: '#87afaf',
  },
} as const satisfies Record<AgentType, AgentPalette>

const AGENT_COLORS_LIGHT = {
  claude: {
    subtle: '#d7af87',
    muted: '#af875f',
    normal: '#875f00',
    highlight: '#000000',
    haze: '#af875f',
  },
  gemini: {
    subtle: '#d787ff',
    muted: '#af5fff',
    normal: '#870087',
    highlight: '#000000',
    haze: '#af5fff',
  },
  codex: {
    subtle: '#87afd7',
    muted: '#5f87af',
    normal: '#005f87',
    highlight: '#000000',
    haze: '#5f8787',
  },
} as const satisfies Record<AgentType, AgentPalette>

/** Mode-resolved agent color map. */
export const AGENT_COLORS: Record<ThemeMode, Record<AgentType, AgentPalette>> = {
  dark: AGENT_COLORS_DARK,
  light: AGENT_COLORS_LIGHT,
}

/** All known agent names. */
export const AGENT_NAMES: readonly AgentType[] = ['claude', 'gemini', 'codex'] as const

/** Default fallback agent when an unknown name is provided. */
export const DEFAULT_AGENT: AgentType = 'codex'

/** Normalize unknown agent names to a stable default. */
export function safeAgent(agent: string): AgentType {
  return AGENT_NAMES.includes(agent as AgentType) ? (agent as AgentType) : DEFAULT_AGENT
}

// ---------------------------------------------------------------------------
// User colors
// ---------------------------------------------------------------------------

export const USER_COLORS = {
  bubbleBg: '#e07030',
  bubbleText: '#ffffff',
} as const

// ---------------------------------------------------------------------------
// Animation palettes
// ---------------------------------------------------------------------------

export const ANIMATION_PALETTES = {
  spectrum: [
    '#ff0000', // Red
    '#ffff00', // Yellow
    '#00ff00', // Green
    '#00ffff', // Cyan
    '#0000ff', // Blue
    '#ff00ff', // Magenta
    '#ffffff', // White
  ],
  fire: [
    '#330000',
    '#661100',
    '#993300',
    '#cc5500',
    '#ff6600',
    '#ff8800',
    '#ffaa00',
    '#ffcc33',
    '#ffee66',
    '#ffffaa',
  ],
  ocean: [
    '#001133',
    '#002255',
    '#003366',
    '#005588',
    '#0077aa',
    '#0099bb',
    '#00bbcc',
    '#00dddd',
    '#66eeee',
    '#aaffff',
  ],
  forest: [
    '#1a0f00',
    '#332200',
    '#3d5c1e',
    '#4a7a23',
    '#55922a',
    '#66aa33',
    '#77bb44',
    '#99cc66',
    '#bbdd88',
    '#ddeebb',
  ],
  sunset: [
    '#ff6633',
    '#ff5544',
    '#ff4466',
    '#ee3388',
    '#cc33aa',
    '#aa33cc',
    '#8833dd',
    '#6644ee',
    '#5555ff',
    '#4477ff',
  ],
  telegram: ['#0000ff', '#ffffff'],
  whatsapp: ['#00ff00', '#ffffff'],
  discord: ['#0000ff', '#ff00ff', '#ffffff'],
  aiKeys: ['#00ff00', '#ffff00'],
  people: ['#ffffff'],
  notifications: ['#ffff00', '#ffffff'],
  environment: ['#00ff00', '#00ffff'],
  validate: ['#00ff00', '#ff0000'],
} as const

export type AnimationPaletteName = keyof typeof ANIMATION_PALETTES

// ---------------------------------------------------------------------------
// Theme mode tokens (Synced with tokens.css)
// ---------------------------------------------------------------------------

const DARK_TOKENS: ThemeTokens = {
  bg: {
    base: '#000000',
    surface: '#262626',
    elevated: '#303030',
    overlay: 'rgba(0, 0, 0, 0.6)',
  },
  text: {
    primary: '#d0d0d0',
    secondary: '#bcbcbc',
    muted: '#808080',
  },
  border: {
    default: '#585858',
    subtle: '#3a3a3a',
    modal: '#bcbcbc',
    input: '#8a8a8a',
  },
  selection: {
    base: '#444444',
    surface: '#4e4e4e',
    elevated: '#585858',
  },
  status: {
    active: '#5faf5f',
    idle: '#585858',
    error: '#ff5f5f',
    ready: '#5faf5f',
    warning: '#d7af00',
  },
  banner: '#585858',
  tabLine: '#585858',
  peaceful: {
    normal: '#bcbcbc',
    muted: '#585858',
  },
  statusBarFg: '#727578',
}

const LIGHT_TOKENS: ThemeTokens = {
  bg: {
    base: '#fdf6e3',
    surface: '#f0ead8',
    elevated: '#e8e0cc',
    overlay: 'rgba(255, 255, 255, 0.6)',
  },
  text: {
    primary: '#303030',
    secondary: '#444444',
    muted: '#808080',
  },
  border: {
    default: '#a8a8a8',
    subtle: '#c6c6c6',
    modal: '#303030',
    input: '#585858',
  },
  selection: {
    base: '#d0d0d0',
    surface: '#c6c6c6',
    elevated: '#bcbcbc',
  },
  status: {
    active: '#008700',
    idle: '#a8a8a8',
    error: '#d70000',
    ready: '#008700',
    warning: '#af8700',
  },
  banner: '#808080',
  tabLine: '#808080',
  peaceful: {
    normal: '#444444',
    muted: '#808080',
  },
  statusBarFg: '#727578',
}

/** Mode-resolved theme tokens. */
export const THEME_TOKENS: Record<ThemeMode, ThemeTokens> = {
  dark: DARK_TOKENS,
  light: LIGHT_TOKENS,
}

// ---------------------------------------------------------------------------
// Haze / blend configuration
// ---------------------------------------------------------------------------

export const HAZE_CONFIG = {
  paneInactive: 0.18,
  paneTreeSelected: 0.08,
  paneActive: 0.0,
  statusAccent: 0.06,
  tuiInactiveLight: 0.06,
  tuiInactiveDark: 0.12,
  terminalHintWeight: 0.35,
} as const

// ---------------------------------------------------------------------------
// Theme detection
// ---------------------------------------------------------------------------

export function detectThemeMode(): ThemeMode {
  if (typeof process !== 'undefined' && process.env?.APPEARANCE_MODE) {
    const env = process.env.APPEARANCE_MODE.trim().toLowerCase()
    if (env === 'light') return 'light'
    if (env === 'dark') return 'dark'
  }
  if (typeof window !== 'undefined' && window.matchMedia) {
    if (window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light'
    }
  }
  return 'dark'
}

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

export function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)))
  return `#${clamp(r).toString(16).padStart(2, '0')}${clamp(g).toString(16).padStart(2, '0')}${clamp(b).toString(16).padStart(2, '0')}`
}

export function blendColors(base: string, overlay: string, pct: number): string {
  const [br, bg, bb] = hexToRgb(base)
  const [or, og, ob] = hexToRgb(overlay)
  return rgbToHex(
    br * (1 - pct) + or * pct,
    bg * (1 - pct) + og * pct,
    bb * (1 - pct) + ob * pct,
  )
}

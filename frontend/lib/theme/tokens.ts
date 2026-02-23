/**
 * Design tokens for the TeleClaude color system.
 *
 * Replaces curses color pair IDs with semantic hex colors. All agent palettes,
 * animation palettes, z-layer backgrounds, and dark/light mode variants live here.
 *
 * No side effects on import.
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
// Agent color palettes
// ---------------------------------------------------------------------------

/**
 * Agent colors in dark mode.
 *
 * Xterm-256 origins (documented for traceability):
 *   Claude:  subtle=94, muted=137, normal=180, highlight=231, haze=#af875f
 *   Gemini:  subtle=103, muted=141, normal=183, highlight=231, haze=#af87ff
 *   Codex:   subtle=67, muted=110, normal=153, highlight=231, haze=#87afaf
 */
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

/**
 * Agent colors in light mode.
 *
 * Xterm-256 origins:
 *   Claude:  subtle=180, muted=137, normal=94, highlight=16, haze=#af875f
 *   Gemini:  subtle=177, muted=135, normal=90, highlight=16, haze=#af5fff
 *   Codex:   subtle=110, muted=67, normal=24, highlight=16, haze=#5f8787
 */
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

/**
 * User message bubble colors.
 *
 * Mode-independent orange accent that gives user messages a distinctive
 * identity in the chat interface.
 */
export const USER_COLORS = {
  bubbleBg: '#e07030',
  bubbleText: '#ffffff',
} as const

// ---------------------------------------------------------------------------
// Animation palettes
// ---------------------------------------------------------------------------

/**
 * Named color arrays for animations.
 *
 * The spectrum palette replaces curses pairs 30-36 (Red, Yellow, Green, Cyan,
 * Blue, Magenta, White). Themed palettes provide smooth gradients with 8+
 * colors generated via HSL interpolation.
 */
export const ANIMATION_PALETTES = {
  /** Full rainbow HSL cycle (replaces curses SpectrumPalette pairs 30-36). */
  spectrum: [
    '#ff0000', // Red
    '#ffff00', // Yellow
    '#00ff00', // Green
    '#00ffff', // Cyan
    '#0000ff', // Blue
    '#ff00ff', // Magenta
    '#ffffff', // White
  ],

  /** Reds, oranges, yellows -- warm combustion gradient. */
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

  /** Blues, teals, cyans -- deep ocean to surf. */
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

  /** Greens, browns -- forest floor to canopy. */
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

  /** Oranges, pinks, purples -- warm to cool horizon. */
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

  /** Section palette: Telegram (Blue, White). */
  telegram: ['#0000ff', '#ffffff'],

  /** Section palette: WhatsApp (Green, White). */
  whatsapp: ['#00ff00', '#ffffff'],

  /** Section palette: Discord (Blue, Magenta, White). */
  discord: ['#0000ff', '#ff00ff', '#ffffff'],

  /** Section palette: AI Keys (Green, Yellow). */
  aiKeys: ['#00ff00', '#ffff00'],

  /** Section palette: People (White). */
  people: ['#ffffff'],

  /** Section palette: Notifications (Yellow, White). */
  notifications: ['#ffff00', '#ffffff'],

  /** Section palette: Environment (Green, Cyan). */
  environment: ['#00ff00', '#00ffff'],

  /** Section palette: Validate (Green, Red). */
  validate: ['#00ff00', '#ff0000'],
} as const

export type AnimationPaletteName = keyof typeof ANIMATION_PALETTES

// ---------------------------------------------------------------------------
// Theme mode tokens
// ---------------------------------------------------------------------------

/**
 * Dark mode token set.
 *
 * Z-layer backgrounds use terminal default (transparent) in curses. In the
 * TypeScript port we provide explicit dark tones for non-terminal contexts
 * while keeping `base` as close to terminal default as possible.
 */
const DARK_TOKENS: ThemeTokens = {
  bg: {
    base: '#000000',
    surface: '#000000',
    elevated: '#000000',
    overlay: 'rgba(0, 0, 0, 0.6)',
  },
  text: {
    primary: '#e4e4e4',    // xterm 254
    secondary: '#bcbcbc',  // xterm 250
    muted: '#808080',      // xterm 244
  },
  border: {
    default: '#585858',    // xterm 240
    subtle: '#3a3a3a',     // xterm 237
    modal: '#bcbcbc',      // xterm 250 -- crisp line
    input: '#8a8a8a',      // xterm 245
  },
  selection: {
    base: '#444444',       // xterm 238
    surface: '#4e4e4e',    // xterm 239
    elevated: '#585858',   // xterm 240
  },
  status: {
    active: '#5faf5f',     // xterm 71
    idle: '#585858',       // xterm 240
    error: '#ff5f5f',      // xterm 203
    ready: '#5faf5f',      // xterm 71
    warning: '#d7af00',    // xterm 178
  },
  banner: '#585858',       // xterm 240
  tabLine: '#585858',      // xterm 240
  peaceful: {
    normal: '#bcbcbc',     // xterm 250 -- 70% gray
    muted: '#585858',      // xterm 240 -- 40% gray
  },
  statusBarFg: '#727578',
}

/**
 * Light mode token set.
 */
const LIGHT_TOKENS: ThemeTokens = {
  bg: {
    base: '#fdf6e3',       // soft paper (matches _LIGHT_MODE_PAPER_BG)
    surface: '#fdf6e3',
    elevated: '#fdf6e3',
    overlay: 'rgba(255, 255, 255, 0.6)',
  },
  text: {
    primary: '#1c1c1c',    // xterm 234
    secondary: '#444444',  // xterm 238
    muted: '#808080',      // xterm 244
  },
  border: {
    default: '#a8a8a8',    // xterm 248
    subtle: '#c6c6c6',     // xterm 251
    modal: '#303030',      // xterm 236 -- crisp line
    input: '#585858',      // xterm 240
  },
  selection: {
    base: '#d0d0d0',       // xterm 252
    surface: '#c6c6c6',    // xterm 251
    elevated: '#bcbcbc',   // xterm 250
  },
  status: {
    active: '#008700',     // xterm 28
    idle: '#a8a8a8',       // xterm 248
    error: '#d70000',      // xterm 160
    ready: '#008700',      // xterm 28
    warning: '#af8700',    // xterm 136
  },
  banner: '#808080',       // xterm 244
  tabLine: '#808080',      // xterm 244
  peaceful: {
    normal: '#444444',     // xterm 238 -- 30% gray
    muted: '#808080',      // xterm 244 -- 60% gray
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

/** Haze blend percentages for tmux pane background theming. */
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

/**
 * Detect the current theme mode at runtime.
 *
 * Precedence:
 *   1. APPEARANCE_MODE env var (terminal context)
 *   2. `prefers-color-scheme` media query (browser context)
 *   3. Dark mode default
 *
 * This function has no side effects and is safe to call repeatedly.
 */
export function detectThemeMode(): ThemeMode {
  // Terminal context: check env var.
  if (typeof process !== 'undefined' && process.env?.APPEARANCE_MODE) {
    const env = process.env.APPEARANCE_MODE.trim().toLowerCase()
    if (env === 'light') return 'light'
    if (env === 'dark') return 'dark'
  }

  // Browser context: check media query.
  if (typeof window !== 'undefined' && window.matchMedia) {
    if (window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light'
    }
  }

  // Default to dark.
  return 'dark'
}

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

/** Convert hex (#RRGGBB) to [r, g, b] tuple (0-255). */
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

/** Convert [r, g, b] tuple (0-255) to #RRGGBB string. */
export function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)))
  return `#${clamp(r).toString(16).padStart(2, '0')}${clamp(g).toString(16).padStart(2, '0')}${clamp(b).toString(16).padStart(2, '0')}`
}

/**
 * Blend two hex colors by a percentage.
 *
 * Formula: result = base * (1 - pct) + overlay * pct
 */
export function blendColors(base: string, overlay: string, pct: number): string {
  const [br, bg, bb] = hexToRgb(base)
  const [or, og, ob] = hexToRgb(overlay)
  return rgbToHex(
    br * (1 - pct) + or * pct,
    bg * (1 - pct) + og * pct,
    bb * (1 - pct) + ob * pct,
  )
}

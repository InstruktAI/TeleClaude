/**
 * Chalk-based color mappers for terminal (Ink) rendering.
 *
 * All functions are curried: `agentColor('claude', 'normal')('text')` returns
 * an orange-colored string.
 *
 * Requires chalk@5+ (ESM). No side effects on import.
 */

import chalk from 'chalk'

import {
  type AgentColorLevel,
  type AgentType,
  type ThemeMode,
  AGENT_COLORS,
  THEME_TOKENS,
  detectThemeMode,
  safeAgent,
} from './tokens.js'

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Lazy-resolved mode so callers don't need to pass it everywhere. */
let _resolvedMode: ThemeMode | null = null

function mode(): ThemeMode {
  if (_resolvedMode === null) {
    _resolvedMode = detectThemeMode()
  }
  return _resolvedMode
}

/** Force a mode refresh (e.g. after a SIGUSR1 theme reload). */
export function resetThemeMode(): void {
  _resolvedMode = null
}

/** Set mode explicitly (useful for testing or forced overrides). */
export function setThemeMode(m: ThemeMode): void {
  _resolvedMode = m
}

// ---------------------------------------------------------------------------
// Agent text colors
// ---------------------------------------------------------------------------

/**
 * Return a chalk formatter for agent-colored text.
 *
 * Usage:
 *   `agentColor('claude', 'normal')('session title')` -- orange text
 */
export function agentColor(
  agent: string,
  level: AgentColorLevel = 'normal',
): (text: string) => string {
  const safe = safeAgent(agent)
  const hex = AGENT_COLORS[mode()][safe][level]
  return (text: string) => chalk.hex(hex)(text)
}

/**
 * Return a chalk formatter that sets the background to the agent's haze color.
 *
 * Primarily intended for tmux pane background simulation in Ink.
 */
export function agentBg(agent: string): (text: string) => string {
  const safe = safeAgent(agent)
  const hex = AGENT_COLORS[mode()][safe].haze
  return (text: string) => chalk.bgHex(hex)(text)
}

// ---------------------------------------------------------------------------
// Status colors
// ---------------------------------------------------------------------------

/** Map well-known session/status strings to theme-aware colors. */
const STATUS_MAP: Record<string, (tokens: typeof THEME_TOKENS.dark) => string> = {
  active:   (t) => t.status.active,
  running:  (t) => t.status.active,
  idle:     (t) => t.status.idle,
  stopped:  (t) => t.status.idle,
  error:    (t) => t.status.error,
  failed:   (t) => t.status.error,
  ready:    (t) => t.status.ready,
  warning:  (t) => t.status.warning,
  pending:  (t) => t.status.warning,
}

/**
 * Return a chalk formatter for status-colored text.
 *
 * Falls back to secondary text color for unrecognized statuses.
 */
export function statusColor(status: string): (text: string) => string {
  const tokens = THEME_TOKENS[mode()]
  const resolver = STATUS_MAP[status.toLowerCase()]
  const hex = resolver ? resolver(tokens) : tokens.text.secondary
  return (text: string) => chalk.hex(hex)(text)
}

// ---------------------------------------------------------------------------
// Theme text
// ---------------------------------------------------------------------------

/**
 * Return a chalk formatter for themed text at a given emphasis level.
 */
export function themeText(
  level: 'primary' | 'secondary' | 'muted',
): (text: string) => string {
  const hex = THEME_TOKENS[mode()].text[level]
  return (text: string) => chalk.hex(hex)(text)
}

// ---------------------------------------------------------------------------
// Supplementary formatters
// ---------------------------------------------------------------------------

/** Banner text (muted). */
export function bannerColor(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].banner
  return (text: string) => chalk.hex(hex)(text)
}

/** Tab line separator color. */
export function tabLineColor(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].tabLine
  return (text: string) => chalk.hex(hex)(text)
}

/** Peaceful-mode normal text (neutral gray, no agent tint). */
export function peacefulNormal(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].peaceful.normal
  return (text: string) => chalk.hex(hex)(text)
}

/** Peaceful-mode muted text (headless sessions, dim content). */
export function peacefulMuted(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].peaceful.muted
  return (text: string) => chalk.hex(hex)(text)
}

/** Border color for modals. */
export function modalBorderColor(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].border.modal
  return (text: string) => chalk.hex(hex)(text)
}

/** Selection background at a given z-layer. */
export function selectionBg(
  zIndex: 0 | 1 | 2 = 0,
): (text: string) => string {
  const tokens = THEME_TOKENS[mode()]
  const layers = [tokens.selection.base, tokens.selection.surface, tokens.selection.elevated] as const
  const hex = layers[zIndex] ?? layers[0]
  return (text: string) => chalk.bgHex(hex)(text)
}

/** Status bar foreground (neutral gray, both modes). */
export function statusBarFg(): (text: string) => string {
  const hex = THEME_TOKENS[mode()].statusBarFg
  return (text: string) => chalk.hex(hex)(text)
}

/**
 * Agent-colored text on agent background (inverted badge style).
 *
 * Replicates the curses A_REVERSE badge rows from the Python TUI where
 * terminal-bg-colored text sits on agent muted/normal backgrounds.
 */
export function agentBadge(
  agent: string,
  focused: boolean = false,
): (text: string) => string {
  const safe = safeAgent(agent)
  const palette = AGENT_COLORS[mode()][safe]
  const bg = focused ? palette.normal : palette.muted
  const fg = mode() === 'dark' ? '#000000' : '#ffffff'
  return (text: string) => chalk.bgHex(bg).hex(fg)(text)
}

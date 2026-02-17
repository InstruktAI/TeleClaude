/**
 * CSS custom property generation for web rendering.
 *
 * Converts the token system from tokens.ts into CSS variables suitable for
 * injection into `document.documentElement.style`.
 *
 * No side effects on import. Call `injectCSSVariables()` explicitly in browser.
 */

import {
  type ThemeMode,
  AGENT_COLORS,
  AGENT_NAMES,
  ANIMATION_PALETTES,
  THEME_TOKENS,
} from './tokens.js'

// ---------------------------------------------------------------------------
// Generator
// ---------------------------------------------------------------------------

/**
 * Generate a flat map of CSS custom properties for the given theme mode.
 *
 * Output format:
 *   `{ '--agent-claude-normal': '#d7af87', '--bg-base': '#000000', ... }`
 *
 * Covers:
 *   - Agent palettes (subtle, muted, normal, highlight, haze)
 *   - Background layers (base, surface, elevated, overlay)
 *   - Text colors (primary, secondary, muted)
 *   - Border colors (default, subtle, modal, input)
 *   - Selection colors (base, surface, elevated)
 *   - Status colors (active, idle, error, ready, warning)
 *   - Misc (banner, tab-line, peaceful, status-bar-fg)
 *   - Animation palettes (indexed)
 */
export function generateCSSVariables(mode: ThemeMode): Record<string, string> {
  const vars: Record<string, string> = {}
  const tokens = THEME_TOKENS[mode]
  const agents = AGENT_COLORS[mode]

  // -- Agent palettes -------------------------------------------------------
  for (const name of AGENT_NAMES) {
    const palette = agents[name]
    vars[`--agent-${name}-subtle`] = palette.subtle
    vars[`--agent-${name}-muted`] = palette.muted
    vars[`--agent-${name}-normal`] = palette.normal
    vars[`--agent-${name}-highlight`] = palette.highlight
    vars[`--agent-${name}-haze`] = palette.haze
  }

  // -- Backgrounds ----------------------------------------------------------
  vars['--bg-base'] = tokens.bg.base
  vars['--bg-surface'] = tokens.bg.surface
  vars['--bg-elevated'] = tokens.bg.elevated
  vars['--bg-overlay'] = tokens.bg.overlay

  // -- Text -----------------------------------------------------------------
  vars['--text-primary'] = tokens.text.primary
  vars['--text-secondary'] = tokens.text.secondary
  vars['--text-muted'] = tokens.text.muted

  // -- Borders --------------------------------------------------------------
  vars['--border-default'] = tokens.border.default
  vars['--border-subtle'] = tokens.border.subtle
  vars['--border-modal'] = tokens.border.modal
  vars['--border-input'] = tokens.border.input

  // -- Selection ------------------------------------------------------------
  vars['--selection-base'] = tokens.selection.base
  vars['--selection-surface'] = tokens.selection.surface
  vars['--selection-elevated'] = tokens.selection.elevated

  // -- Status ---------------------------------------------------------------
  vars['--status-active'] = tokens.status.active
  vars['--status-idle'] = tokens.status.idle
  vars['--status-error'] = tokens.status.error
  vars['--status-ready'] = tokens.status.ready
  vars['--status-warning'] = tokens.status.warning

  // -- Misc -----------------------------------------------------------------
  vars['--banner'] = tokens.banner
  vars['--tab-line'] = tokens.tabLine
  vars['--peaceful-normal'] = tokens.peaceful.normal
  vars['--peaceful-muted'] = tokens.peaceful.muted
  vars['--status-bar-fg'] = tokens.statusBarFg

  // -- Animation palettes ---------------------------------------------------
  for (const [paletteName, colors] of Object.entries(ANIMATION_PALETTES)) {
    for (let i = 0; i < colors.length; i++) {
      vars[`--anim-${paletteName}-${i}`] = colors[i]
    }
    vars[`--anim-${paletteName}-length`] = String(colors.length)
  }

  return vars
}

// ---------------------------------------------------------------------------
// Browser injection
// ---------------------------------------------------------------------------

/**
 * Write all CSS variables for the given mode onto `document.documentElement`.
 *
 * Browser-only. Calling this in a Node/terminal context is a no-op.
 */
export function injectCSSVariables(mode: ThemeMode): void {
  if (typeof document === 'undefined') return

  const vars = generateCSSVariables(mode)
  const style = document.documentElement.style

  for (const [prop, value] of Object.entries(vars)) {
    style.setProperty(prop, value)
  }
}

/**
 * Remove all TeleClaude CSS variables from `document.documentElement`.
 *
 * Useful when switching themes to avoid stale properties.
 * Browser-only; no-op in Node.
 */
export function clearCSSVariables(): void {
  if (typeof document === 'undefined') return

  const style = document.documentElement.style

  // Generate a full set for dark mode (the key names are the same for both
  // modes) and remove each property.
  const vars = generateCSSVariables('dark')
  for (const prop of Object.keys(vars)) {
    style.removeProperty(prop)
  }
}

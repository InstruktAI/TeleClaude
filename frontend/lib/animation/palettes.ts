/**
 * Animation palette utilities.
 *
 * Re-exports ANIMATION_PALETTES from the theme token layer and adds
 * animation-specific helpers for palette selection.
 *
 * No side effects on import.
 */

import {
  AGENT_COLORS,
  AGENT_NAMES,
  ANIMATION_PALETTES,
  detectThemeMode,
  type AgentType,
  type AnimationPaletteName,
} from '@/lib/theme/tokens'

// ---------------------------------------------------------------------------
// Re-exports
// ---------------------------------------------------------------------------

export { ANIMATION_PALETTES }
export type { AnimationPaletteName }

// ---------------------------------------------------------------------------
// Palette names
// ---------------------------------------------------------------------------

/** All available palette names. */
export const PALETTE_NAMES = Object.keys(ANIMATION_PALETTES) as AnimationPaletteName[]

/** Palettes suitable for full-banner animations (8+ colors for smooth gradients). */
export const GRADIENT_PALETTE_NAMES: AnimationPaletteName[] = [
  'spectrum',
  'fire',
  'ocean',
  'forest',
  'sunset',
]

/** Palettes intended for config-section animations (2-3 colors). */
export const SECTION_PALETTE_NAMES: AnimationPaletteName[] = [
  'telegram',
  'whatsapp',
  'discord',
  'aiKeys',
  'people',
  'notifications',
  'environment',
  'validate',
]

// ---------------------------------------------------------------------------
// Lookup helpers
// ---------------------------------------------------------------------------

/**
 * Retrieve a named palette as a hex string array.
 *
 * Returns the spectrum palette when the name is unrecognized.
 */
export function getPaletteByName(name: string): string[] {
  const palette = ANIMATION_PALETTES[name as AnimationPaletteName]
  if (palette) return [...palette]
  return [...ANIMATION_PALETTES.spectrum]
}

/**
 * Retrieve the agent-specific animation palette (subtle, muted, normal, highlight).
 *
 * Mode-aware: uses the current theme mode to select dark/light variants.
 */
export function getAgentPalette(agent: AgentType): string[] {
  const mode = detectThemeMode()
  const colors = AGENT_COLORS[mode][agent]
  return [colors.subtle, colors.muted, colors.normal, colors.highlight]
}

/**
 * Pick a random gradient palette (suitable for banner animations).
 */
export function getRandomPalette(): string[] {
  const idx = Math.floor(Math.random() * GRADIENT_PALETTE_NAMES.length)
  return getPaletteByName(GRADIENT_PALETTE_NAMES[idx])
}

/**
 * Pick a random palette suitable for a given agent, with a bias toward the
 * agent's own colors (50% chance agent palette, 50% random gradient).
 */
export function getRandomAgentPalette(agent: AgentType): string[] {
  if (Math.random() < 0.5) return getAgentPalette(agent)
  return getRandomPalette()
}

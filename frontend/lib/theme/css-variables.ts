/**
 * CSS custom property utilities.
 * 
 * NOTE: Core variables are now statically defined in lib/theme/tokens.css
 * and imported via globals.css.
 */

import {
  type ThemeMode,
  THEME_TOKENS,
} from './tokens'

/**
 * Browser-only helper to manually apply variables if needed for
 * dynamic overrides outside the static tokens.css system.
 */
export function applyTeleClaudeVariables(mode: ThemeMode): void {
  if (typeof document === 'undefined') return
  
  const tokens = THEME_TOKENS[mode]
  const style = document.documentElement.style
  
  style.setProperty('--tc-bg-base', tokens.bg.base)
  style.setProperty('--tc-text-primary', tokens.text.primary)
  // ... add more if runtime injection is ever required again
}

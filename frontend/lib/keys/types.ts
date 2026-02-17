/**
 * Keyboard binding types and interfaces for TeleClaude TUI
 *
 * This module defines the type system for keyboard bindings shared between
 * terminal (Ink) and web (browser) versions of the TUI.
 */

/**
 * View context where a key binding is active
 */
export type ViewContext = 'global' | 'sessions' | 'preparation' | 'configuration'

/**
 * A single keyboard binding definition
 *
 * Bindings are pure data - they describe WHAT keys do WHERE, not HOW.
 * The action handlers are connected separately in view components.
 */
export interface KeyBinding {
  /** The key character or name ('q', 'upArrow', 'space', etc.) */
  key: string

  /** Requires Ctrl modifier */
  ctrl?: boolean

  /** Requires Shift modifier */
  shift?: boolean

  /** Requires Meta/Alt modifier */
  meta?: boolean

  /** Human-readable description for help/footer */
  description: string

  /** Action identifier (e.g., 'quit', 'navigate_up', 'toggle_sticky') */
  action: string

  /** Where this binding is active */
  context: ViewContext

  /** Don't show in footer/help display */
  hidden?: boolean
}

/**
 * Ink's useInput key input structure
 * Used for mapping between Ink and our binding system
 */
export interface InkKeyInput {
  upArrow: boolean
  downArrow: boolean
  leftArrow: boolean
  rightArrow: boolean
  return: boolean
  escape: boolean
  tab: boolean
  backspace: boolean
  delete: boolean
  pageUp: boolean
  pageDown: boolean
}

/**
 * Modifier keys that can be pressed with a key
 */
export interface KeyModifiers {
  ctrl?: boolean
  shift?: boolean
  meta?: boolean
}

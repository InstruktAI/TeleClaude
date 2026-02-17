/**
 * Complete keyboard binding map for TeleClaude TUI
 *
 * Defines ALL keyboard shortcuts for:
 * - Global actions (available in all views)
 * - Sessions view
 * - Preparation view
 * - Configuration view
 *
 * Bindings are derived from the Python curses TUI:
 * - teleclaude/cli/tui/app.py (global bindings)
 * - teleclaude/cli/tui/views/sessions.py (sessions view)
 * - teleclaude/cli/tui/views/preparation.py (preparation view)
 * - teleclaude/cli/tui/views/configuration.py (configuration view)
 */

import { KeyBinding, ViewContext, KeyModifiers } from './types'

/**
 * All keyboard bindings in the application
 */
export const BINDINGS: KeyBinding[] = [
  // ========================================================================
  // GLOBAL BINDINGS (active in all views)
  // ========================================================================
  {
    key: 'q',
    description: 'Quit',
    action: 'quit',
    context: 'global',
  },
  {
    key: '1',
    description: 'Sessions tab',
    action: 'switch_to_sessions',
    context: 'global',
  },
  {
    key: '2',
    description: 'Preparation tab',
    action: 'switch_to_preparation',
    context: 'global',
  },
  {
    key: '3',
    description: 'Configuration tab',
    action: 'switch_to_configuration',
    context: 'global',
  },
  {
    key: 'r',
    description: 'Refresh',
    action: 'refresh_data',
    context: 'global',
  },
  {
    key: 'm',
    description: 'Anim mode',
    action: 'toggle_animation_mode',
    context: 'global',
  },
  {
    key: 'c',
    description: 'Colors',
    action: 'toggle_pane_theming',
    context: 'global',
  },
  {
    key: 'v',
    description: 'TTS',
    action: 'toggle_tts',
    context: 'global',
  },
  {
    key: '+',
    description: 'Expand all',
    action: 'expand_all',
    context: 'global',
  },
  {
    key: '=',
    description: 'Expand all',
    action: 'expand_all',
    context: 'global',
    hidden: true, // Same as + but no shift required
  },
  {
    key: '-',
    description: 'Collapse all',
    action: 'collapse_all',
    context: 'global',
  },
  {
    key: 'escape',
    description: 'Back',
    action: 'go_back',
    context: 'global',
  },

  // ========================================================================
  // SESSIONS VIEW BINDINGS
  // ========================================================================
  {
    key: 'upArrow',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'sessions',
  },
  {
    key: 'k',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'sessions',
    hidden: true, // Vi-style, same as upArrow
  },
  {
    key: 'downArrow',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'sessions',
  },
  {
    key: 'j',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'sessions',
    hidden: true, // Vi-style, same as downArrow
  },
  {
    key: 'leftArrow',
    description: 'Collapse/Back',
    action: 'collapse_or_back',
    context: 'sessions',
  },
  {
    key: 'rightArrow',
    description: 'Drill down/Expand',
    action: 'drill_down',
    context: 'sessions',
  },
  {
    key: ' ',
    description: 'Preview',
    action: 'space_action',
    context: 'sessions',
  },
  {
    key: 'return',
    description: 'Focus',
    action: 'activate_session',
    context: 'sessions',
  },
  {
    key: 'n',
    description: 'New session',
    action: 'new_session',
    context: 'sessions',
  },
  {
    key: 'a',
    description: 'Open/Close sessions',
    action: 'toggle_project_sessions',
    context: 'sessions',
  },
  {
    key: 'A',
    description: 'Open/Close sessions',
    action: 'toggle_project_sessions',
    context: 'sessions',
    hidden: true, // Same as lowercase a
  },
  {
    key: 'k',
    description: 'Kill session',
    action: 'kill_session',
    context: 'sessions',
  },
  {
    key: 'R',
    shift: true,
    description: 'Restart agent',
    action: 'restart_agent',
    context: 'sessions',
  },
  {
    key: 'pageUp',
    description: 'Scroll page up',
    action: 'page_up',
    context: 'sessions',
  },
  {
    key: 'pageDown',
    description: 'Scroll page down',
    action: 'page_down',
    context: 'sessions',
  },

  // ========================================================================
  // PREPARATION VIEW BINDINGS
  // ========================================================================
  {
    key: 'upArrow',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'preparation',
  },
  {
    key: 'k',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'preparation',
    hidden: true, // Vi-style, same as upArrow
  },
  {
    key: 'downArrow',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'preparation',
  },
  {
    key: 'j',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'preparation',
    hidden: true, // Vi-style, same as downArrow
  },
  {
    key: ' ',
    description: 'Preview file',
    action: 'preview_file',
    context: 'preparation',
  },
  {
    key: 'return',
    description: 'Open in editor',
    action: 'open_editor',
    context: 'preparation',
  },
  {
    key: 's',
    description: 'Start work',
    action: 'start_work',
    context: 'preparation',
  },
  {
    key: 'p',
    description: 'Prepare todo',
    action: 'prepare_todo',
    context: 'preparation',
  },
  {
    key: 'v',
    description: 'View file',
    action: 'view_file',
    context: 'preparation',
  },
  {
    key: 'e',
    description: 'Edit file',
    action: 'edit_file',
    context: 'preparation',
  },
  {
    key: 'c',
    description: 'Clear preview',
    action: 'clear_preview',
    context: 'preparation',
  },
  {
    key: 'pageUp',
    description: 'Scroll page up',
    action: 'page_up',
    context: 'preparation',
  },
  {
    key: 'pageDown',
    description: 'Scroll page down',
    action: 'page_down',
    context: 'preparation',
  },

  // ========================================================================
  // CONFIGURATION VIEW BINDINGS
  // ========================================================================
  {
    key: 'upArrow',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'configuration',
  },
  {
    key: 'k',
    description: 'Navigate up',
    action: 'navigate_up',
    context: 'configuration',
    hidden: true, // Vi-style, same as upArrow
  },
  {
    key: 'downArrow',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'configuration',
  },
  {
    key: 'j',
    description: 'Navigate down',
    action: 'navigate_down',
    context: 'configuration',
    hidden: true, // Vi-style, same as downArrow
  },
  {
    key: 'leftArrow',
    description: 'Previous subtab',
    action: 'prev_subtab',
    context: 'configuration',
  },
  {
    key: 'h',
    description: 'Previous subtab',
    action: 'prev_subtab',
    context: 'configuration',
    hidden: true, // Vi-style, same as leftArrow
  },
  {
    key: 'rightArrow',
    description: 'Next subtab',
    action: 'next_subtab',
    context: 'configuration',
  },
  {
    key: 'l',
    description: 'Next subtab',
    action: 'next_subtab',
    context: 'configuration',
    hidden: true, // Vi-style, same as rightArrow
  },
  {
    key: 'return',
    description: 'Select/Toggle',
    action: 'select_item',
    context: 'configuration',
  },
  {
    key: 'tab',
    description: 'Next tab',
    action: 'next_tab',
    context: 'configuration',
  },
  {
    key: 'tab',
    shift: true,
    description: 'Previous tab',
    action: 'prev_tab',
    context: 'configuration',
  },
]

/**
 * Get all bindings for a specific context
 */
export function getBindingsForContext(context: ViewContext): KeyBinding[] {
  return BINDINGS.filter(
    (binding) => binding.context === context || binding.context === 'global'
  )
}

/**
 * Find a binding that matches the key and modifiers in a specific context
 */
export function findBinding(
  key: string,
  modifiers: KeyModifiers,
  context: ViewContext
): KeyBinding | undefined {
  const contextBindings = getBindingsForContext(context)

  return contextBindings.find((binding) => {
    // Key must match exactly
    if (binding.key !== key) return false

    // Check modifiers (undefined/false are equivalent)
    const ctrlMatch = (binding.ctrl ?? false) === (modifiers.ctrl ?? false)
    const shiftMatch = (binding.shift ?? false) === (modifiers.shift ?? false)
    const metaMatch = (binding.meta ?? false) === (modifiers.meta ?? false)

    return ctrlMatch && shiftMatch && metaMatch
  })
}

/**
 * Get footer hints for a specific context (non-hidden bindings only)
 */
export function getFooterHints(
  context: ViewContext
): Array<{ key: string; description: string }> {
  const contextBindings = getBindingsForContext(context)

  // Filter out hidden bindings and format for footer display
  return contextBindings
    .filter((binding) => !binding.hidden)
    .map((binding) => {
      // Format key with modifiers for display
      let displayKey = binding.key
      if (binding.ctrl) displayKey = `Ctrl+${displayKey}`
      if (binding.shift) displayKey = `Shift+${displayKey}`
      if (binding.meta) displayKey = `Meta+${displayKey}`

      // Map special keys to readable names
      const keyMap: Record<string, string> = {
        upArrow: '↑',
        downArrow: '↓',
        leftArrow: '←',
        rightArrow: '→',
        return: 'Enter',
        escape: 'Esc',
        pageUp: 'PgUp',
        pageDown: 'PgDn',
        ' ': 'Space',
      }
      displayKey = keyMap[displayKey] ?? displayKey

      return {
        key: displayKey,
        description: binding.description,
      }
    })
}

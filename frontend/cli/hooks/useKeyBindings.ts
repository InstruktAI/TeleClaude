/**
 * Global + view-specific keyboard handler for the TUI.
 *
 * Bridges Ink's `useInput` hook with the declarative binding map from
 * `@/lib/keys/bindings.ts`. Callers pass a context (which view is active)
 * and a handler map keyed by action name; this hook takes care of matching
 * the physical keypress to the right action.
 */

import { useInput } from "ink";

import { findBinding } from "@/lib/keys/bindings.js";
import type { InkKeyInput, KeyModifiers, ViewContext } from "@/lib/keys/types.js";

// ---------------------------------------------------------------------------
// Key name resolution
// ---------------------------------------------------------------------------

/**
 * Derive the canonical key name that our binding map uses from Ink's input
 * callback arguments.
 *
 * Ink delivers special keys via boolean flags on the `key` object and
 * printable characters via the `input` string.
 */
function resolveKeyName(input: string, key: InkKeyInput): string {
  if (key.upArrow) return "upArrow";
  if (key.downArrow) return "downArrow";
  if (key.leftArrow) return "leftArrow";
  if (key.rightArrow) return "rightArrow";
  if (key.return) return "return";
  if (key.escape) return "escape";
  if (key.tab) return "tab";
  if (key.backspace) return "backspace";
  if (key.delete) return "delete";
  if (key.pageUp) return "pageUp";
  if (key.pageDown) return "pageDown";

  // Printable character (or space)
  return input;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Register keyboard handlers for the active view context.
 *
 * @param context  - The view currently displayed (determines which bindings
 *                   are eligible alongside the always-active `global` set).
 * @param handlers - Map of action name to callback. Only actions with a
 *                   matching handler are invoked; unhandled actions are
 *                   silently ignored.
 */
export function useKeyBindings(
  context: ViewContext,
  handlers: Record<string, () => void>,
): void {
  useInput((input: string, key: InkKeyInput) => {
    const keyName = resolveKeyName(input, key);
    if (!keyName) return;

    // Ink does not surface shift/meta/ctrl directly on printable keys.
    // For modifier detection we check:
    //   ctrl  - Ink passes ctrl+<char> as the raw control code in `input`;
    //           however the `key` object does not expose a `.ctrl` flag.
    //           We pass `false` and rely on bindings using ctrl to use Ink's
    //           built-in character mapping (e.g. ctrl+c = \x03).
    //   shift - Uppercase letters or symbols imply shift; we detect via case.
    //   meta  - Not reliably reported by most terminals inside tmux.
    const modifiers: KeyModifiers = {
      ctrl: false,
      shift: input.length === 1 && input >= "A" && input <= "Z",
      meta: false,
    };

    const binding = findBinding(keyName, modifiers, context);
    if (!binding) return;

    const handler = handlers[binding.action];
    if (handler) {
      handler();
    }
  });
}

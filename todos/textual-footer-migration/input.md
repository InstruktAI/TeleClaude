# Input: textual-footer-migration

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->

## Problem

The current `ActionBar` widget uses hardcoded strings per view to display key hints. This requires manual sync between each view's `BINDINGS` list and the `ActionBar._CONTEXT_BAR` / `_SESSION_CONTEXT` dicts. We just shipped `todo-remove-cli-option` with the `R` keybinding registered in `BINDINGS` but invisible in the TUI because the ActionBar string wasn't updated. The builder, reviewer, and demo all missed it.

This class of bug is eliminated by using Textual's built-in `Footer` widget, which auto-discovers bindings from the focused widget and its ancestors.

## User Requirements

- **Dynamic binding display**: When a binding is added to any view's `BINDINGS`, it must appear in the footer automatically. No hardcoded string maintenance.
- **Compact / C64-style**: Reduce screen real estate. Current footer area is 4 lines (3 ActionBar + 1 StatusBar). Target: 2 lines (1 Footer + 1 StatusBar). Use Unicode symbols for keys and binding groups to compress related keys.
- **Beautiful styling**: Style key portion differently from description. Keys bold/accent, descriptions dimmed. Should integrate with the existing TeleClaude theming system.
- **Keep everything visible**: Don't hide bindings. Users should be able to learn all available keys from the footer. Make it fit by being denser, not by hiding.
- **Sessions view cursor-context**: The sessions view currently changes hints based on cursor position (session row vs computer row vs project row). This must be preserved using dynamic `Binding.show` toggling.
- **Preparation view cursor-context**: Similarly, the todo tree must show/hide actions based on whether a TodoRow or TodoFileRow is selected.

## Research Findings (Dynamic Context)

### Intra-widget Context Sensitivity

Textual's `Footer` widget switches context when _focus_ moves. However, `SessionsView` and `PreparationView` are single widgets where the _internal selection_ (cursor) changes.

To support this:

1.  **Reactive Watcher**: Use `watch_cursor_index(self, index: int)` in the view to call `self.app.refresh_bindings()`.
2.  **`check_action` override** (public API): Override `check_action(self, action, parameters) -> bool | None` to return `True`/`False` based on current item type. This is Textual's documented mechanism for [dynamic actions](https://textual.textualize.io/guide/actions#dynamic-actions).
3.  **Signal Refresh**: `refresh_bindings()` triggers Footer to re-evaluate `check_action` for all bindings.

**Important**: `Binding` is a **frozen dataclass** — `binding.show = val` raises `FrozenInstanceError`. Do NOT attempt to mutate bindings directly. Use `check_action` instead.

Example pattern:

```python
def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
    if action in ("kill_session", "restart_session"):
        item = self._current_item()
        return isinstance(item, SessionRow)
    return True

def watch_cursor_index(self, index: int) -> None:
    # ... existing cursor visual update logic ...
    self.app.refresh_bindings()
```

This avoids the complex `ActionBar` messaging chain while providing the same (or better) context sensitivity.

### Automatic Binding Discovery

- Footer reads `self.screen.active_bindings` — merges bindings from focused widget + all ancestors
- Subscribes to `self.screen.bindings_updated_signal` for live updates
- Context-sensitive by default: focus changes trigger footer recompose

### Binding Groups (`Binding.Group`)

Groups let related keys share a single description label:

```python
nav_group = Binding.Group(description="Nav", compact=True)
BINDINGS = [
    Binding("up", "cursor_up", "", group=nav_group, key_display="\u2191"),
    Binding("down", "cursor_down", "", group=nav_group, key_display="\u2193"),
]
# Renders as grouped: up-arrow down-arrow Nav
```

### CSS Component Classes (on FooterKey)

```css
FooterKey .footer-key--key {
  /* style the key label */
}
FooterKey .footer-key--description {
  /* style the description */
}
```

Additional selectors: `FooterKey.-compact`, `FooterKey.-grouped`, `FooterKey.-disabled`, `FooterKey.-command-palette`, `FooterLabel`, `KeyGroup`, `KeyGroup.-compact`.

### Design Token CSS Variables

`$footer-foreground`, `$footer-background`, `$footer-key-foreground`, `$footer-key-background`, `$footer-description-foreground`, `$footer-description-background`, `$footer-item-background`

### key_display

- Plain string only (no Rich markup), but Unicode symbols work perfectly
- Override globally via `App.get_key_display(binding)`
- Examples: arrows for navigation, return symbol for enter, space symbol for space, +/- for expand/collapse

### Compact Mode

`Footer(compact=True)` removes padding around keys. Saves ~2 cells per binding.

### Subclassing

Can subclass `Footer` and override `compose()` while keeping auto-discovery. `FooterKey`, `FooterLabel`, `KeyGroup` are importable from `textual.widgets._footer` (private API — pin Textual version).

### Important Implementation Notes

- Footer is a `ScrollableContainer` with `layout: horizontal` and `scrollbar-size: 0 0`. Overflowing bindings scroll horizontally.
- `_bindings_ready` guard in `compose()` prevents rendering before bindings are available.
- `data_bind(compact=Footer.compact)` is needed when yielding FooterKey from custom compose.
- Current Textual version in project: 8.0.0

## Current Architecture

### Files involved

- `teleclaude/cli/tui/widgets/action_bar.py` — custom ActionBar (DELETE)
- `teleclaude/cli/tui/widgets/footer.py` — legacy curses Footer class (already unused by Textual app)
- `teleclaude/cli/tui/app.py` — composes ActionBar + StatusBar in footer area
- `teleclaude/cli/tui/telec.tcss` — CSS for #footer, ActionBar, StatusBar
- `teleclaude/cli/tui/messages.py` — `CursorContextChanged` message
- `teleclaude/cli/tui/views/preparation.py` — BINDINGS uses tuples
- `teleclaude/cli/tui/views/sessions.py` — BINDINGS uses tuples, posts CursorContextChanged
- `teleclaude/cli/tui/views/jobs.py` — BINDINGS uses tuples
- `teleclaude/cli/tui/views/config.py` — BINDINGS uses tuples

### Current BINDINGS format (all views use tuples)

```python
BINDINGS = [
    ("up", "cursor_up", "Previous"),
    ("R", "remove_todo", "Remove"),
]
```

Must be migrated to `Binding` objects for `key_display`, `group`, and `show` support.

### Sessions view cursor-context challenge

`SessionsView` posts `CursorContextChanged(item_type="session"|"computer"|"project")` and ActionBar switches between `_SESSION_CONTEXT` dicts. With Textual Footer, this is solved via `check_action` and `refresh_bindings()`.

- **Computer Node**:
  - `n` (New Session) must be hidden (not possible).
  - `R` (Restart) should become "Restart All".
- **Project Node**:
  - `n` (New Session) is the default action.
- **Session Node**:
  - Standard nav/kill/restart.

### Preparation view rich context

- **Project Node**:
  - `n` (New Todo) is the default action.
  - Hide `R` (Remove Todo) and `Enter` hint.
- **File Node**:
  - `Enter` = Edit, `Space` = Preview.
  - Inherit parent context: `R` should still work to remove the parent to-do. This is implemented by allowing `remove_todo` action when on a file node, resolving the parent todo slug.

### Default Action Indicator

Indicate the primary action (the one triggered by `Enter`) by making its binding **bold** in the footer.

- Bold both the key and the label.
- Eliminate the redundant `[Enter]` hint if the primary key is visually distinct.
- Technical implementation: Use custom IDs for primary bindings or a description prefix that the CSS can target.

### Workflow: Modal First

"Prepare" (p) and "Start work" (s) should always open `StartSessionModal` pre-filled with the appropriate command (`/next-prepare` or `/next-work`).

- This allows the user to review/adjust the agent and thinking mode before dispatching.
- If on a Project node, the slug is omitted (letting the machine resolve from roadmap).
- If on a Todo node, the slug is pre-filled.

## Design Direction

- Replace ActionBar with `Footer(compact=True, show_command_palette=False)`
- Convert all view BINDINGS from tuples to `Binding` objects
- Use `Binding.Group(compact=True)` for navigation keys (up/down/left/right) and expand/collapse (+/-)
- Use `key_display` with Unicode symbols for common keys
- Style via CSS component classes + design token variables integrated with TeleClaude theming
- Indication: Bold default action bindings.
- Net result: 4 lines to 2 lines footer area

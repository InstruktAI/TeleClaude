# Review Findings: tui-footer-polish

## Paradigm-Fit Assessment

1. **Data flow**: Implementation correctly uses `telec roadmap move` CLI via subprocess, consistent with how `action_new_project` uses `telec config patch`. Post-mutation `_refresh_data()` triggers full tree rebuild. Follows established pattern.
2. **Component reuse**: `_format_binding_item()` modified in-place as required. `check_action()` extended using the same gating pattern. No copy-paste duplication found.
3. **Pattern consistency**: Bindings use the same `Binding()` constructor. Actions follow `action_*` naming. Error handling uses `self.app.notify()` with severity. All consistent with adjacent code.

## Critical

None.

## Important

### 1. Cursor does not follow moved item after Shift+Up/Down

**File:** `teleclaude/cli/tui/views/preparation.py:581, 611`

After a successful `telec roadmap move`, `_refresh_data()` triggers `_rebuild()` which clears and remounts all widgets. The `cursor_index` stays at the same numeric position, but the item that was there has moved away. This means:

- **Shift+Up**: The item moves to position N-1, but cursor stays at N — now pointing at the item that slid down. Visually confusing; repeated Shift+Up reorders different items each time instead of moving the same item progressively.
- **Shift+Down**: Same issue in reverse.

**Fix**: Adjust `cursor_index` before calling `_refresh_data()`:

```python
# In action_move_todo_up, after successful subprocess:
if self.cursor_index > 0:
    self.cursor_index -= 1
self.app._refresh_data()

# In action_move_todo_down, after successful subprocess:
if self.cursor_index < len(self._nav_items) - 1:
    self.cursor_index += 1
self.app._refresh_data()
```

This ensures the cursor follows the moved item through rebuilds, matching the expected UX for list reordering (SC-8, SC-9).

## Suggestions

### 1. Redundant branches in `_format_binding_item()` could be collapsed

**File:** `teleclaude/cli/tui/widgets/telec_footer.py:98-103`

The `not enabled` and `dim` branches produce identical styles (`Style(bold=True, dim=True)`). Could be simplified to:

```python
key_style = Style(bold=True, dim=(not enabled or dim))
```

Functionally correct as-is; purely a readability note.

### 2. Blocking subprocess.run in move actions

**File:** `teleclaude/cli/tui/views/preparation.py:570-576, 600-606`

`subprocess.run()` blocks the event loop during Shift+Up/Down. In practice `telec roadmap move` is a fast local YAML operation (<50ms), and the existing codebase uses blocking subprocess in comparable action handlers (`action_new_project`). No regression, but converting to `asyncio.create_subprocess_exec` would eliminate any stuttering during rapid repeated reordering.

## Requirements Trace

| SC    | Status  | Evidence                                                                                                          |
| ----- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| SC-1  | Pass    | `NewProjectModal #modal-box { width: 60; max-height: 20; }` in `telec.tcss:372-375`                               |
| SC-2  | Pass    | `StartSessionModal #modal-box { width: 64; max-height: 32; }` unchanged — already compact                         |
| SC-3  | Pass    | `Style(bold=True)` without explicit color; terminal default adapts to light theme                                 |
| SC-4  | Pass    | Same mechanism; bold without color renders bright in dark theme                                                   |
| SC-5  | Pass    | `key_display` changed from unicode symbols to `"q"`, `"r"`, `"t"` in `app.py:94,127-128`                          |
| SC-6  | Pass    | `Binding("a", "cycle_animation", "Anim")` in `app.py:129`; handler cycles off→periodic→party                      |
| SC-7  | Pass    | `Binding("v", "toggle_tts", "Voice")` in `app.py:130`; `s` conflict documented                                    |
| SC-8  | Partial | Shift+Up moves item in roadmap ✓, but cursor doesn't follow (see Important #1)                                    |
| SC-9  | Partial | Shift+Down moves item in roadmap ✓, but cursor doesn't follow (see Important #1)                                  |
| SC-10 | Pass    | `check_action` gates `move_todo_up/down` — disabled on non-root nodes, ComputerHeader, ProjectHeader, TodoFileRow |
| SC-11 | Pass    | Actions call `telec roadmap move --before/--after` via subprocess, then `_refresh_data()`                         |
| SC-12 | Pass    | Regression audit documented in implementation-plan.md; all 12 prior criteria verified                             |
| SC-13 | Pass    | Builder reports 2426 tests passed, lint clean                                                                     |

## Test Coverage Assessment

No new unit tests added. Builder justified this as all changes being UI/widget-level (CSS rules, key_display labels, action delegation). Existing guardrail tests (`test_create_todo_modal.py`, `test_no_fallbacks.py`) still pass. The behavioral gap (cursor not following moved item) would not have been caught by unit tests regardless — it's a UX integration concern.

## Verdict: REQUEST CHANGES

One Important finding: cursor must follow the moved item on Shift+Up/Down to satisfy SC-8 and SC-9 intent. The fix is a 2-line change per action method.

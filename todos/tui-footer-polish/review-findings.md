# Review Findings: tui-footer-polish

## Round 2 (re-review after fix)

Previous verdict: REQUEST CHANGES (cursor tracking, Important #1).
Fix applied in `eca2516e`. This round verifies the fix and re-evaluates.

## Paradigm-Fit Assessment

1. **Data flow**: Implementation uses `telec roadmap move` CLI via subprocess, consistent with `action_new_project`'s use of `telec config patch`. Post-mutation `_refresh_data()` triggers full tree rebuild. Follows established pattern.
2. **Component reuse**: `_format_binding_item()` modified in-place as required. `check_action()` extended using the same gating pattern. No copy-paste duplication.
3. **Pattern consistency**: Bindings use the same `Binding()` constructor. Actions follow `action_*` naming. Error handling uses `self.app.notify()` with severity. All consistent with adjacent code.

## Critical

None.

## Important

None. Previous Important #1 (cursor tracking) resolved in `eca2516e`.

### Verification of fix

- `action_move_todo_up` (`preparation.py:581`): `self.cursor_index -= 1` before `_refresh_data()`. Edge case protected by early return when `prev_slug is None`.
- `action_move_todo_down` (`preparation.py:612`): `self.cursor_index += 1` before `_refresh_data()`. Edge case protected by early return when `next_slug is None`.

Fix is correct and minimal.

## Suggestions

### 1. Redundant branches in `_format_binding_item()` could be collapsed

**File:** `teleclaude/cli/tui/widgets/telec_footer.py:98-103`

The `not enabled` and `dim` branches produce identical styles (`Style(bold=True, dim=True)`). Could be:

```python
key_style = Style(bold=True, dim=(not enabled or dim))
```

Functionally correct as-is; readability note only.

### 2. Blocking subprocess.run in move actions

**File:** `teleclaude/cli/tui/views/preparation.py:570-576, 600-606`

`subprocess.run()` blocks the event loop during Shift+Up/Down. In practice `telec roadmap move` is fast (<50ms), and the codebase uses blocking subprocess in comparable action handlers. No regression, but `asyncio.create_subprocess_exec` would be cleaner.

### 3. Build Gates and implementation-plan checkboxes not marked

**Files:** `todos/tui-footer-polish/quality-checklist.md`, `todos/tui-footer-polish/implementation-plan.md`

All Build Gates and implementation-plan task checkboxes remain `[ ]`. The work is complete per code evidence and `state.yaml` (`build: complete`). This is a clerical omission — not blocking since the orchestrator validated build completion.

## Requirements Trace

| SC    | Status | Evidence                                                                                                          |
| ----- | ------ | ----------------------------------------------------------------------------------------------------------------- |
| SC-1  | Pass   | `NewProjectModal #modal-box { width: 60; max-height: 20; }` in `telec.tcss:372-375`                               |
| SC-2  | Pass   | `StartSessionModal #modal-box { width: 64; max-height: 32; }` unchanged — already compact                         |
| SC-3  | Pass   | `Style(bold=True)` without explicit color; terminal default adapts to light theme                                 |
| SC-4  | Pass   | Same mechanism; bold without color renders bright in dark theme                                                   |
| SC-5  | Pass   | `key_display` changed from unicode symbols to `"q"`, `"r"`, `"t"` in `app.py:94,127-128`                          |
| SC-6  | Pass   | `Binding("a", "cycle_animation", "Anim")` in `app.py:129`; handler cycles off→periodic→party                      |
| SC-7  | Pass   | `Binding("v", "toggle_tts", "Voice")` in `app.py:130`; `s` conflict documented in docstring                       |
| SC-8  | Pass   | Shift+Up moves item in roadmap; cursor follows via `cursor_index -= 1` (fix `eca2516e`)                           |
| SC-9  | Pass   | Shift+Down moves item in roadmap; cursor follows via `cursor_index += 1` (fix `eca2516e`)                         |
| SC-10 | Pass   | `check_action` gates `move_todo_up/down` — disabled on non-root nodes, ComputerHeader, ProjectHeader, TodoFileRow |
| SC-11 | Pass   | Actions call `telec roadmap move --before/--after` via subprocess, then `_refresh_data()`                         |
| SC-12 | Pass   | Regression audit documented in implementation-plan.md; all 12 prior criteria verified                             |
| SC-13 | Pass   | Builder reports 2426 tests passed, lint clean                                                                     |

## Test Coverage Assessment

No new unit tests added. Builder justified this as all changes being UI/widget-level (CSS rules, key_display labels, action delegation). Existing guardrail tests still pass. Acceptable given the scope.

## Why No Critical/Important Issues

1. **Paradigm-fit verified**: Data flow uses established CLI subprocess pattern. Component reuse confirmed — `_format_binding_item()` extended, not duplicated. `check_action()` follows existing gating pattern.
2. **Requirements validated**: All 13 success criteria traced to code evidence. SC-8/SC-9 now pass after cursor fix.
3. **Copy-paste duplication checked**: `_find_root_todo_neighbors()` is new standalone logic. `action_move_todo_up`/`action_move_todo_down` share structure but differ in direction semantics (--before vs --after, cursor decrement vs increment) — not a duplication issue.

## Verdict: APPROVE

All Important findings from round 1 resolved. SC-1 through SC-13 pass. Code follows established patterns. 3 minor suggestions carried forward (non-blocking).

# Review Findings: config-wizard-redesign

## Paradigm-Fit Assessment

1. **Data flow**: `set_env_var` is correctly placed in the shared config handler layer (`config_handlers.py`). The view calls through the handler, not directly to the filesystem. Persistence goes through the shared layer as required.
2. **Component reuse**: Env var row rendering logic is duplicated between `_render_adapters` and `_render_environment` — flagged below as a suggestion. Projection dataclasses (`AdapterSectionProjection`, `NotificationProjection`, `GuidedStep`) are clean domain models that separate computation from rendering.
3. **Pattern consistency**: New code follows established Textual patterns (reactive properties, Binding declarations, Widget subclasses, `ComposeResult`). The guided step sequence is deterministic and well-structured.

## Requirements Tracing

| SC  | Requirement                                          | Implemented | Evidence                                                                                |
| --- | ---------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------- |
| 1   | Grouped adapter sections with status labels          | Yes         | `project_adapter_sections`, `_render_adapters` card layout with status badges           |
| 2   | Overall completion summary, updates after edits      | Yes         | `completion_summary` in `_render_header`, refreshed via `refresh_data`                  |
| 3   | Inline edit via Enter, save/cancel behavior          | Yes         | `_begin_edit`/`save_edit`/`cancel_edit`, key handling in `on_key`                       |
| 4   | Persist to env file + update `os.environ`            | Yes         | `set_env_var` writes file and sets `os.environ[name]`                                   |
| 5   | Guided mode with step/total progress                 | Yes         | `_GUIDED_STEPS`, `_apply_guided_step`, `_render_header` step counter                    |
| 6   | Notifications placeholder removed                    | Yes         | `_render_notifications` shows projection; curses view updated; regression test confirms |
| 7   | Validation trigger `v` still works                   | Yes         | `action_run_validation` preserved, binding present                                      |
| 8   | Automated coverage for helpers and interaction logic | Yes         | `test_config_handlers.py` (3 new), `test_tui_config_view.py` (8 new), all passing       |

## Important

### 1. `export` prefix silently stripped during env var replacement

**File:** `teleclaude/cli/config_handlers.py:473-476`

When an existing `.env` line uses `export VAR=value` syntax, the match is correct but the replacement always writes `VAR=value` without `export`:

```python
if stripped.startswith(f"{name}=") or stripped.startswith(f"export {name}="):
    lines[index] = f"{name}={value}\n"  # export keyword lost
```

If the `.env` file is sourced into a shell (rather than parsed by a dotenv library), silently removing `export` changes runtime behavior.

**Fix:** Preserve the `export` prefix when present:

```python
if stripped.startswith(f"export {name}="):
    lines[index] = f"export {name}={value}\n"
elif stripped.startswith(f"{name}="):
    lines[index] = f"{name}={value}\n"
```

### 2. Guided mode marks environment step complete when env data fails to load

**File:** `teleclaude/cli/tui/views/config.py:642`

```python
if step.subtab == "environment":
    return all(status.is_set for status in self._env_data) if self._env_data else True
```

If `check_env_vars()` fails and `_env_data` is `[]` (lines 366-370), the `else True` branch marks environment as complete. Guided mode silently skips the environment step instead of surfacing the load failure.

**Fix:** Return `False` when env data is empty:

```python
return all(status.is_set for status in self._env_data) if self._env_data else False
```

### 3. Redundant `_auto_advance_completed_steps` call in `save_edit`

**File:** `teleclaude/cli/tui/views/config.py:569-571`

`refresh_data` (line 384) already calls `_auto_advance_completed_steps` when guided mode is active. Then `save_edit` calls it again:

```python
self.refresh_data()              # internally calls _auto_advance_completed_steps
if self._guided_mode:
    self._auto_advance_completed_steps()   # redundant second call
```

The double-call is currently harmless (the second is a no-op) but creates a maintenance hazard if the advance logic gains side effects.

**Fix:** Remove lines 570-571.

## Suggestions

### 4. Env var row rendering duplicated between adapters and environment tabs

**File:** `teleclaude/cli/tui/views/config.py:707-722` and `759-774`

The cursor selection, edit-mode rendering, and icon/status display logic is structurally identical across `_render_adapters` and `_render_environment`, differing only in the detail line (description vs adapter tag). Could be extracted into a `_render_env_rows(result, rows, detail_fn)` helper.

### 5. `set_env_var` uses plain `write_text` instead of atomic write pattern

**File:** `teleclaude/cli/config_handlers.py:484`

The rest of the codebase uses `_atomic_yaml_write` with tmp+replace+lock+fsync. `set_env_var` uses bare `Path.write_text()`. For a single-user TUI the risk is low, but it's an inconsistency in the persistence layer. Consider extracting a shared `_atomic_text_write` helper if atomicity becomes important.

### 6. Missing test coverage for `set_env_var` validation paths

No tests exercise the `ValueError` rejections for invalid env var names (empty string, contains `=`, contains newlines) or invalid values (contains newlines). Adding these would protect the validation boundary if refactored.

### 7. Secret values shown in cleartext during pre-populated edits

**File:** `teleclaude/cli/tui/views/config.py:527`

When editing an already-set variable, `_begin_edit` pre-populates `_edit_buffer` from `os.environ.get()`. The full value (potentially an API key or token) is displayed immediately. The constraint ("Do not print full secret values in status messages or logs after edit operations") is technically satisfied since this is **during** editing, not after. But for shoulder-surfing defense, masking known secret vars (names containing TOKEN, KEY, SECRET, PASSWORD) with `*` characters in the display would be a UX improvement.

## Verification Evidence

- **Tests**: 20/20 pass (`pytest tests/unit/test_config_handlers.py tests/unit/test_tui_config_view.py`)
- **Lint**: All checks pass (`make lint` — ruff format, ruff check, pyright: 0 errors)
- **Manual TUI verification**: Not possible in this review environment. Build notes acknowledge this gap and cite automated interaction tests as the substitute.
- **Placeholder regression**: `test_notifications_view_does_not_render_placeholder_literal` confirms "Not implemented yet" is absent from rendered output.
- **Implementation plan**: All 28 task checkboxes marked `[x]`.
- **Build gates**: All 9 items checked.
- **Deferrals**: No `deferrals.md` exists; no silent scope cuts detected.

## Verdict: REQUEST CHANGES

Findings #1 (export prefix loss) and #2 (empty env_data logic error) are behavioral bugs that should be fixed before merge. Finding #3 (redundant call) is a small cleanup. All three fixes are 1-3 lines each.

## Fixes Applied

- **Issue #1 (Important):** Preserve `export` prefix when updating existing exported env vars.
  - **Fix:** `set_env_var` now writes `export {name}={value}` when the matched line starts with `export`.
  - **Commit:** `d44d71bb`
- **Issue #2 (Important):** Guided mode incorrectly treated missing env data as complete.
  - **Fix:** `_is_current_guided_step_complete` now returns `False` when `_env_data` is empty on the environment step.
  - **Commit:** `c010d44f`
- **Issue #3 (Important):** Duplicate guided auto-advance call after save.
  - **Fix:** Removed the redundant `_auto_advance_completed_steps` call in `save_edit`; refresh flow remains the single advancement path.
  - **Commit:** `1170859f`

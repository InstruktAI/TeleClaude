# Review Findings — tui-config-experience

**Review round:** 1
**Verdict:** REQUEST CHANGES
**Scope:** 46 files changed, +2158 / -1521 lines. Animation engine refactor, Config tab implementation, old CLI tool removal.
**Tests:** 1671 passed, 0 failed.

---

## Critical

### C1. Palette lookup mismatch for adapter sections

**Files:** `animation_triggers.py:148`, `animation_colors.py:127-133`

`StateDrivenTrigger.set_context()` looks up palettes using the full `section_id` (e.g., `"adapters.telegram"`), but the palette registry registers palettes with short names (`"telegram"`). All four adapter section animations silently fall back to the generic spectrum palette, defeating section-specific coloring entirely.

**Fix:** Strip the `adapters.` prefix before palette lookup:

```python
palette_key = section_id.split(".")[-1] if "." in section_id else section_id
palette = palette_registry.get(palette_key)
```

### C2. Empty list causes index corruption

**Files:** `adapters.py:113-114`, `people.py:63-64`, `environment.py:58-59`, `validate.py:94-95`

When `env_vars` is empty (WhatsApp component: `env_vars_keys=[]`), `max_idx = len(self.env_vars) - 1` becomes `-1`. Pressing Down arrow sets `selected_index = -1`, corrupting internal state. The same structural issue exists in all four scrollable components.

**Fix:** Guard against empty lists in KEY_DOWN handlers:

```python
if not self.env_vars:
    return True
```

### C3. Deleted TestConfigHandlers without replacement

**Files:** deleted `test_config_interactive.py` (440 lines), live `config_handlers.py`

`TestConfigHandlers` (13 tests) covered the shared data layer (`config_handlers.py`) which is still actively used by both CLI and TUI paths. Functions now without direct unit test coverage: `get_global_config` default behavior, `get_person_config`, `save_global_config` atomic round-trip, `_atomic_yaml_write` cleanup, `discover_config_areas`, `list_person_dirs`. The CLI integration tests in `test_config_cli.py` provide partial indirect coverage but do not replace the deleted unit tests.

**Fix:** Restore `TestConfigHandlers` into a new `tests/unit/test_config_handlers.py`.

### C4. New reducer intents have zero test coverage

**Files:** `state.py:450-470` (3 new reducers), `test_tui_state.py` (no new tests)

Three new `IntentType` values (`SET_ANIMATION_MODE`, `SET_CONFIG_SUBTAB`, `SET_CONFIG_GUIDED_MODE`) with validation logic (type checks, membership checks) have no tests. The existing `test_tui_state.py` covers all pre-existing reducers but none of the new ones.

**Fix:** Add tests for all three new reducers to `test_tui_state.py`, including happy path and invalid input cases.

---

## Important

### I1. StateDrivenTrigger accesses engine.\_targets (private state)

**Files:** `animation_triggers.py:171-174`

Direct access to `self.engine._targets.get(target)` to set `slot.looping = True`. Violates encapsulation — the engine's public API (`play`, `stop`, `update`, `get_color`) does not expose this. The comment acknowledges the violation.

**Fix:** Add `set_looping(target, looping)` to `AnimationEngine`.

### I2. `callback: Any` in four config components

**Files:** `people.py:18`, `validate.py:18`, `environment.py:18`, `notifications.py:18`

The base class defines `callback: ConfigComponentCallback` (Protocol), but four concrete subclasses use `Any`, defeating structural type checking. Only `AdapterConfigComponent` uses the correct type.

**Fix:** Replace `Any` with `ConfigComponentCallback` in all four constructors.

### I3. `animation_mode: str` should be `Literal`

**Files:** `state.py:90`, `state.py:132` (IntentPayload)

`animation_mode: str = "periodic"` with valid values documented only in a comment. The implementation plan explicitly called for `Literal["off", "periodic", "party"]`. The `load_sticky_state` function loads from JSON with no validation — a corrupted file could set an invalid mode.

**Fix:** Change to `Literal["off", "periodic", "party"]` and add validation in `load_sticky_state`.

### I4. `active_subtab: str` should be `Literal`

**Files:** `state.py` (ConfigViewState)

Same pattern as I3. The `SET_CONFIG_SUBTAB` reducer only checks `isinstance(subtab, str)` but does not validate membership, unlike `SET_ANIMATION_MODE` which validates the value set.

**Fix:** Type as `Literal["adapters", "people", "notifications", "environment", "validate"]` and add membership check in the reducer.

### I5. `validate_all()` exceptions leave `validating=True` permanently

**Files:** `validate.py:102-109`

`run_validation()` sets `self.validating = True`, then calls `validate_all()`. Any unexpected exception (PermissionError, OSError) propagates without resetting the flag. The component gets stuck showing "Validating... Please wait." permanently.

**Fix:** Use `try/finally` to ensure `validating` is always reset.

### I6. Missing whatsapp section palette

**Files:** `animation_colors.py:127-133`

Palettes registered for telegram, discord, ai_keys, people, notifications, environment, validate — but not for whatsapp. Inconsistent with the pattern established for other adapters.

**Fix:** Add `palette_registry.register(SectionPalette("whatsapp", [2, 6]))`.

### I7. Dead code path for Enter in guided mode

**Files:** `configuration.py:183-186`

`handle_key()` has a separate Enter handler for guided mode (lines 183-186), but Enter is handled globally in `app.py` and dispatched via `handle_enter()`. The code in `handle_key()` is unreachable dead code that creates maintenance risk.

**Fix:** Remove the Enter handling from `handle_key()` guided mode branch.

### I8. `selected_index` not clamped after data refresh

**Files:** `people.py:72-74`, `environment.py:66-67`

`on_focus()` refreshes the data list but does not clamp `selected_index`. If the list shrank, the stale index causes `IndexError` on the next render.

**Fix:** Clamp `selected_index` after refresh: `self.selected_index = min(self.selected_index, max(0, len(items) - 1))`.

### I9. Dead fields in ConfigViewState

**Files:** `state.py` (ConfigViewState)

`selected_field_index` and `scroll_offset` are declared but never read or written through the reducer. Each `ConfigComponent` maintains its own independent selection state. These fields are misleading.

**Fix:** Remove unused fields or wire them to the active component.

---

## Suggestions

### S1. Scroll tracking uses hardcoded heuristic

**Files:** `adapters.py:122`, `validate.py`, `people.py`, `environment.py`

`if self.selected_index > self.scroll_offset + 5` uses a magic number. Scrolling will break for terminal heights that differ from the assumed size.

### S2. `check_env_vars()` called every render frame

**Files:** `adapters.py:55`

Called on every render cycle (~10Hz). Cache the result and refresh on `on_focus()`.

### S3. Broad `curses.error` catch wraps component delegation

**Files:** `configuration.py:232-236`

The entire render body is wrapped in a single `try/except curses.error: pass`, including component delegation and animation notifications. Non-curses bugs in component rendering would be silently swallowed.

### S4. I/O at construction time in PeopleConfigComponent

**Files:** `people.py:20`

`list_people()` reads from disk in `__init__`. A corrupt config file crashes `ConfigurationView.__init__`, making the entire TUI unusable. Defer to `on_focus()` or wrap with error handling.

### S5. `on_focus()` refresh has no error handling

**Files:** `people.py:72`, `environment.py:66`

If the config file was corrupted between focus events, the exception propagates through the TUI event loop.

### S6. File lock failure silently swallowed

**Files:** `config_handlers.py:196-199`

Lock acquisition failure is caught with `except OSError: pass`. At minimum, log a warning.

### S7. `RenderTarget` and `FieldGuidance` should be frozen

**Files:** `pixel_mapping.py`, `guidance.py`

Both are write-once data. `@dataclass(frozen=True)` would enforce immutability.

### S8. No per-target exception handling in animation engine update loop

**Files:** `animation_engine.py:119-160`

An exception in any animation's `update()` crashes the engine for all targets. Wrap per-target with try/except.

### S9. Zero-width target causes division errors in config animations

**Files:** `animations/config.py:33,55`

`PulseAnimation.update()` divides by `width`; `TypingAnimation.update()` calls `random.randint(0, width - 1)`. Both crash if a target has zero width.

---

## Test Coverage Gaps (from test analyzer)

| Priority | Gap                                     | Recommended Action                                |
| -------- | --------------------------------------- | ------------------------------------------------- |
| 9/10     | Config handlers unit tests deleted      | Restore into `tests/unit/test_config_handlers.py` |
| 8/10     | New reducer intents untested            | Add to `tests/unit/test_tui_state.py`             |
| 7/10     | StateDrivenTrigger untested             | Add to `tests/unit/test_animations.py`            |
| 7/10     | CLI dispatch for new TUI config path    | Add to `tests/unit/test_config_cli.py`            |
| 6/10     | Custom-target animation engine API      | Add to `tests/unit/test_animations.py`            |
| 5/10     | Config animation classes                | Basic smoke tests                                 |
| 5/10     | `animation_mode` persistence round-trip | State store tests                                 |

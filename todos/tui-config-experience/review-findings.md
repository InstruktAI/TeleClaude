# Review Findings — tui-config-experience

**Review round:** 2
**Verdict:** REQUEST CHANGES
**Scope:** Fix commit ff0cd2ce — 12 files changed, +192 / -26 lines. Addresses round 1 findings.
**Tests:** 82 passed, 0 failed. Lint clean (ruff + pyright).

---

## Round 1 Resolution Status

### Critical — All Resolved

| ID  | Finding                                        | Status                                                                                   |
| --- | ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| C1  | Palette lookup mismatch for adapter sections   | RESOLVED — prefix stripping added in `animation_triggers.py:149`                         |
| C2  | Empty list causes index corruption             | RESOLVED — guards added in all 4 scrollable components                                   |
| C3  | Deleted TestConfigHandlers without replacement | RESOLVED — `test_config_handlers.py` added with 8 tests covering all 6 flagged functions |
| C4  | New reducer intents have zero test coverage    | RESOLVED — 3 new test functions in `test_tui_state.py` with valid + invalid inputs       |

### Important — 9 of 11 Resolved, 2 Remain

| ID  | Finding                                             | Status                                                                               |
| --- | --------------------------------------------------- | ------------------------------------------------------------------------------------ |
| I1  | `StateDrivenTrigger` accesses `engine._targets`     | **NOT RESOLVED** — see below                                                         |
| I2  | `callback: Any` in four components                  | RESOLVED — all four use `ConfigComponentCallback`                                    |
| I3  | `animation_mode: str` should be `Literal`           | RESOLVED — `Literal["off", "periodic", "party"]` + validation in `load_sticky_state` |
| I4  | `active_subtab: str` should be `Literal`            | RESOLVED — `Literal[...]` + membership check in reducer                              |
| I5  | `validate_all()` exception leaves `validating=True` | RESOLVED — `try/finally` added                                                       |
| I6  | Missing whatsapp section palette                    | RESOLVED — palette registered                                                        |
| I7  | Dead Enter handler in guided mode                   | **NOT RESOLVED** — see below                                                         |
| I8  | `selected_index` not clamped after data refresh     | RESOLVED — clamping added in `people.py` and `environment.py`                        |
| I9  | Dead fields in `ConfigViewState`                    | RESOLVED — `selected_field_index` and `scroll_offset` removed                        |

Additionally resolved: S4 (I/O at construction in PeopleConfigComponent) — deferred to `on_focus()`.

---

## Remaining Findings

### Important

#### I1 (round 1, unfixed). `StateDrivenTrigger` still accesses `engine._targets` directly

**Files:** `animation_triggers.py:171-176`

The fix commit added `AnimationEngine.set_looping(target, looping)` (public API) at `animation_engine.py:119-122`, but `StateDrivenTrigger` still uses the private attribute directly:

```python
# animation_triggers.py:171-176
if is_idle:
    slot = self.engine._targets.get(target)
    if slot:
        slot.looping = True
```

The stale comment at line 171 even acknowledges the violation. The public method exists but is unused.

**Fix:** Replace lines 171-176 with:

```python
if is_idle:
    self.engine.set_looping(target, True)
```

#### I7 (round 1, unfixed). Dead Enter handler in `handle_key()`

**Files:** `views/configuration.py:183-185`

Enter (key == 10) is intercepted in `app.py:1037` and dispatched to `view.handle_enter()`. It never reaches `handle_key()`. Lines 183-185 are dead code:

```python
# configuration.py:183-185
if key == 10:  # Enter -> Next step
    self._advance_guided_mode()
```

The Esc handler at lines 186-189 in the same block IS reachable.

**Fix:** Remove lines 183-185 (the `if key == 10` branch). Keep the Esc handler. Restructure to:

```python
# Guided mode Esc handler
if self.state.config.guided_mode and key == 27:
    self.controller.dispatch(Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": False}))
    if self.notify:
        self.notify("Exited guided mode", NotificationLevel.INFO)
```

---

## Suggestions (not blocking)

### S1. `# type: ignore` comments lack explanatory suffixes

**Files:** `state.py:457,463`, `state_store.py:60`

Three bare `# type: ignore` comments. The reason (mypy can't narrow `str` to `Literal` through `in` checks) is inferrable from context, but per linting policy, suppressions should include a concise reason.

**Consider:** `# type: ignore[assignment]  # narrowed by membership check above`

### S2. C1 palette fix has no regression test

**Files:** `animation_triggers.py:149`

The palette prefix-stripping fix (`section_id.split(".")[-1]`) is untested. A `StateDrivenTrigger` test verifying that `"adapters.telegram"` resolves to the `"telegram"` palette would prevent regression.

### S3. `IntentPayload.mode` and `.subtab` remain `str` instead of `Literal`

**Files:** `state.py:151-152`

The state fields were correctly narrowed to `Literal`, but the corresponding `IntentPayload` fields remain `str`. These should match: `mode: Literal["off", "periodic", "party"]` and `subtab: Literal["adapters", "people", "notifications", "environment", "validate"]`. This would eliminate the need for `# type: ignore` at the assignment sites.

---

## Verdict: REQUEST CHANGES

Two Important findings from round 1 remain unfixed. Both are trivial (1-2 line changes each). All Critical findings resolved. Tests and lint pass.

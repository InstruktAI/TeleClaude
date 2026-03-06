# Implementation Plan: clickable-sprites

## Overview

Three-phase approach: first make the sprite system robust and contributor-friendly
(validation, graceful degradation), then add attribution metadata and clickability,
then document the authoring flow. This order ensures the foundation is solid before
adding interactive features.

## Phase 1: Robust Sprite Loading and TUI Startup Resilience

### Task 1.1: Surface sprite validation errors on startup

**File(s):** `teleclaude/cli/tui/animations/sprites/__init__.py`

- [ ] Wrap `get_sky_entities()` iteration in try/except per-sprite, catching
      `ValueError`, `TypeError`, and `Exception` from sprite construction
      (e.g., `SpriteGroup.__post_init__` weight validation).
- [ ] On error: log the exception with the sprite name/module AND print a
      user-visible warning to stderr: `"[telec] Sprite error in {name}: {error}"`.
- [ ] Continue loading remaining sprites — one bad sprite should not prevent
      the rest from appearing.
- [ ] Apply the same error isolation to `get_sprite_groups()` and
      `get_weather_clouds()`.

### Task 1.2: Graceful TUI startup without daemon

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/telec.py`

- [ ] In `TelecApp.on_mount()`: the `api.connect()` call already has a
      try/except. Verify that a failed connection does not prevent the TUI
      from rendering — animations and banner must still work.
- [ ] In `_refresh_data()`: already catches exceptions. Verify the views
      show meaningful empty state (not a crash) when the daemon is unreachable.
- [ ] In `main()` (telec.py line ~1495-1500): the startup exception handler
      logs to the log file only. Add a `print()` to stderr so the user sees
      startup crash info even if logging is not configured:
      `print(f"telec TUI crashed: {e}", file=sys.stderr)`.

### Task 1.3: Logging resilience when log directory is absent

**File(s):** `teleclaude/logging_config.py`

- [ ] Investigate `instrukt_ai_logging.configure_logging("teleclaude")` behavior
      when `/var/log/instrukt-ai/teleclaude/` does not exist. If it raises,
      wrap it in try/except and fall back to stderr-only logging with a warning.
- [ ] This is critical for first-run and contributor scenarios where the system
      log directory hasn't been provisioned.

---

## Phase 2: Source URL Metadata and Clickable Sprites

### Task 2.1: Add `source_url` field to sprite dataclasses

**File(s):** `teleclaude/cli/tui/animations/sprites/composite.py`

- [ ] Add `source_url: Optional[str] = None` to `CompositeSprite` (frozen dataclass).
- [ ] Add `source_url: Optional[str] = None` to `AnimatedSprite` (frozen dataclass).
- [ ] Add `source_url: Optional[str] = None` to `SpriteGroup` (frozen dataclass).
- [ ] Update `CompositeSprite.resolve_colors()` to preserve `source_url` in the copy.

### Task 2.2: Populate source URLs for existing sprites

**File(s):** `teleclaude/cli/tui/animations/sprites/ufo.py`,
`teleclaude/cli/tui/animations/sprites/birds.py`,
`teleclaude/cli/tui/animations/sprites/cars.py`,
`teleclaude/cli/tui/animations/sprites/clouds.py`,
`teleclaude/cli/tui/animations/sprites/celestial.py`

- [ ] Audit each sprite file to determine its origin (original creation in
      this repo vs. adapted from external source).
- [ ] Add `source_url="https://github.com/InstruktAI/TeleClaude/blob/main/teleclaude/cli/tui/animations/sprites/<file>.py"`
      for sprites authored in this repo.
- [ ] For any sprites adapted from external sources, use the external repo URL.

### Task 2.3: Track sky entity positions for click hit-testing

**File(s):** `teleclaude/cli/tui/animations/general.py`

- [ ] In `GlobalSky.update()`, after rendering each sky entity, record its
      bounding box: `(x_start, y_start, x_end, y_end, sprite_ref)` in a
      list `self._entity_bounds`.
- [ ] Clear `_entity_bounds` at the start of each `update()` call.
- [ ] Add a `hit_test(x: int, y: int) -> Optional[str]` method that checks
      `_entity_bounds` (front-to-back Z-order) and returns the `source_url`
      of the first entity that contains the click position.

### Task 2.4: Handle click events on the Banner widget

**File(s):** `teleclaude/cli/tui/widgets/banner.py`

- [ ] Add `on_click(self, event: Click)` handler to the `Banner` class.
- [ ] Map the click's `(event.x, event.y)` to the banner's pixel coordinate
      system (accounting for compact mode offset).
- [ ] Call the animation engine's sky animation's `hit_test()` with the
      mapped coordinates. Note: the `AnimationEngine` does not currently expose
      a reference to `GlobalSky`. The builder must add a path (e.g., a property
      or method on the engine) to reach the `GlobalSky` instance for hit-testing.
- [ ] If a `source_url` is returned, call `webbrowser.open(source_url)`.

### Task 2.5: Replace `_show_animation_toast` with attribution callback

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] The `_show_animation_toast` is already a no-op. Remove the callback
      assignment (`self._animation_engine.on_animation_start = self._show_animation_toast`)
      unless it's needed for other purposes.
- [ ] Optionally: use the callback to show a brief status bar hint
      ("Click sprite to view source") when a sprite with a `source_url` enters
      the viewport. This is a nice-to-have.

---

## Phase 3: Contributor Documentation and Validation

### Task 3.1: Write sprite authoring guide

**File(s):** `teleclaude/cli/tui/animations/sprites/CONTRIBUTING.md` (new file)

- [ ] Document the sprite file format: `CompositeSprite`, `SpriteLayer`,
      `AnimatedSprite`, `SpriteGroup`.
- [ ] Show a minimal example (copy of a simple sprite like `WISP_1`).
- [ ] Explain required fields: `layers`, `z_weights`, `y_weights`, `speed_weights`.
- [ ] Explain `source_url` and attribution expectations.
- [ ] Explain the auto-discovery mechanism: add to `__init__.py` `__all__`.
- [ ] Explain how to test: run `telec`, press `a` to cycle animations,
      press `u` for UFO.

### Task 3.2: Tests

- [ ] Add unit test for `get_sky_entities()` with a malformed sprite (verify
      it returns remaining valid sprites and logs the error).
- [ ] Add unit test for `source_url` field on `CompositeSprite` and `AnimatedSprite`.
- [ ] Add unit test for `hit_test()` method on `GlobalSky`.
- [ ] Run `make test`.

### Task 3.3: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).

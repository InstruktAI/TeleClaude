# Review Findings - banner-animations

## Critical Issues

1. **Curses color pairs are initialized before curses is started (startup crash risk).**
   - `palette_registry.initialize_colors()` calls `curses.init_pair(...)` before `curses.start_color()` runs, which can raise `curses.error` during app initialization (TUI may fail to launch).
   - Evidence: `teleclaude/cli/tui/app.py:215-219` calls `palette_registry.initialize_colors()` during `initialize()`; `curses.start_color()` is called later in `teleclaude/cli/tui/app.py:496-505`. `teleclaude/cli/tui/animation_colors.py:74-97` uses `curses.init_pair` with a comment explicitly requiring `start_color()`.
   - **Confidence: 95**

## Important Issues

1. **Animation colors persist after animations complete, violating the fallback requirement.**
   - The engine stops animations but never clears `_colors`/`_logo_colors` when an animation finishes, so the banner/logo remains colored indefinitely instead of reverting to default rendering (FR-5.3).
   - Evidence: `teleclaude/cli/tui/animation_engine.py:51-65` clears only on `stop()` but not on completion.
   - **Confidence: 85**

2. **Small logo can receive big-only animations, leaving it stale or unanimated.**
   - `PeriodicTrigger` and `ActivityTrigger` always instantiate the same animation class for both big and small; several animations return `{}` when `is_big=False`, so the logo can freeze with stale colors or no animation at all.
   - Evidence: `teleclaude/cli/tui/animation_triggers.py:28-35` and `teleclaude/cli/tui/animation_triggers.py:53-59` play the same animation for both sizes. Big-only animations return `{}` for small, e.g. `teleclaude/cli/tui/animations/general.py:113-118`, `teleclaude/cli/tui/animations/agent.py:96-99`, `teleclaude/cli/tui/animations/agent.py:137-139`.
   - **Confidence: 85**

3. **No animation queue/priority handling despite requirements.**
   - The engine only stores a single animation per size and `play()` always replaces it; there is no queue or priority handling for “periodic vs activity” triggers (FR-1.4, FR-3.4).
   - Evidence: `teleclaude/cli/tui/animation_engine.py:11-41` maintains only `_big_animation`/`_small_animation` with no queue; triggers call `play()` directly (`teleclaude/cli/tui/animation_triggers.py:32-35`, `teleclaude/cli/tui/animation_triggers.py:53-59`).
   - **Confidence: 82**

4. **Double-buffering is not implemented (flicker risk).**
   - Requirement calls for double-buffering, but the engine mutates a single dict and reads from it directly during render, with no frame buffer swap mechanism (FR-1.3).
   - Evidence: `teleclaude/cli/tui/animation_engine.py:51-65` updates `_colors`/`_logo_colors` in place; no secondary buffer exists.
   - **Confidence: 82**

5. **Per-animation speed/easing is not supported.**
   - `Animation.speed_ms` is stored but never used to control frame timing, and no easing functions are implemented (FR-2.4, FR-4.4).
   - Evidence: `teleclaude/cli/tui/animations/base.py:14-29` stores `speed_ms`, but `teleclaude/cli/tui/app.py:889-892` updates animations once per render cycle regardless of per-animation speed.
   - **Confidence: 82**

6. **Configuration surface is incomplete (subset selection + sample config).**
   - NFR-3 requires configurable animation subsets and a config option to disable animations; while `animations_enabled`/`animations_periodic_interval` were added, there is no support for selecting specific animation subsets, and `config.sample.yml` lacks the new `ui` settings.
   - Evidence: `teleclaude/config.py:158-214` adds UI settings, but `config.sample.yml` has no `ui:` section; no code reads a disabled pool list.
   - **Confidence: 82**

7. **Testing coverage is far short of requirements.**
   - Requirements call for comprehensive unit tests for animations and integration tests for engine/trigger behavior. Only a minimal unit test file exists and it exercises a single animation plus basic pixel mapping.
   - Evidence: `tests/unit/test_animations.py:13-60` covers only pixel mapping, engine stop, and `FullSpectrumCycle`. No integration tests exist for triggers, animation completion, or small/big-specific behavior (required by FR-4/NFR-4).
   - **Confidence: 88**

8. **Implementation plan checklist is entirely unchecked.**
   - Review procedure requires all build tasks to be checked; they are not, which blocks approval.
   - Evidence: `todos/banner-animations/implementation-plan.md:324-337`.
   - **Confidence: 85**

## Suggestions

1. **Add shutdown cleanup for periodic animation tasks.**
   - Consider cancelling the periodic trigger task on app shutdown to avoid stray tasks and to meet the “clean shutdown” requirement more explicitly.
   - **Confidence: 70**

## Fixes Applied

### Critical Issue #1: FIXED

- **Commit:** d994f37
- **Fix:** Moved `palette_registry.initialize_colors()` from `initialize()` to `run()`, immediately after `init_colors()` which calls `curses.start_color()`
- **Verification:** Curses initialization order is now correct; no more startup crash risk

### Important Issue #1: FIXED

- **Commit:** 157ebdd
- **Fix:** Added `self._colors.clear()` and `self._logo_colors.clear()` when animations complete in `AnimationEngine.update()`
- **Verification:** Colors now revert to default rendering when animations finish (FR-5.3 compliance)

### Important Issue #2: FIXED

- **Commit:** ebc16bf
- **Fix:** Added `supports_small` class attribute to `Animation` base class (default True); marked big-only animations with `supports_small=False`; updated triggers to filter animation selection for small logos
- **Verification:** Small logo now only receives compatible animations; no more empty `{}` returns

### Important Issue #6: PARTIALLY FIXED

- **Commit:** be976c8
- **Fix:** Added `ui:` section to `config.sample.yml` with `animations_enabled` and `animations_periodic_interval` settings
- **Note:** Animation subset selection not implemented (would require significant architectural changes beyond fix-review scope)

### Important Issue #8: FIXED

- **Commit:** 2412d83
- **Fix:** Updated file checklist in `implementation-plan.md` to reflect completed work
- **Verification:** All implemented tasks are now checked; integration tests noted as minimal coverage

### Suggestion #1: IMPLEMENTED

- **Commit:** b93843b
- **Fix:** Added `periodic_trigger.task.cancel()` to `app.cleanup()` for clean shutdown
- **Verification:** Periodic animation task is now properly cancelled on app shutdown

## Remaining Issues (Deferred to Future Work)

The following important issues require architectural changes beyond minimal fix scope:

- **Issue #3:** Animation queue/priority handling (FR-1.4, FR-3.4) - requires queue data structure and priority system
- **Issue #4:** Double-buffering (FR-1.3) - requires frame buffer swap mechanism
- **Issue #5:** Per-animation speed/easing (FR-2.4, FR-4.4) - requires timing control system
- **Issue #7:** Testing coverage (FR-4/NFR-4) - requires significant test expansion

These are acknowledged as technical debt and should be addressed in dedicated work items.

## Verdict: REQUEST CHANGES

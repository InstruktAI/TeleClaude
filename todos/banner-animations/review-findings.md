# Review Findings - banner-animations

## Critical Issues

1. **Animations do not advance without user/WS events (no steady render tick).**
   - `animation_engine.update()` is only called inside `_render`, and `_render` only runs on keypress or when a WebSocket/pane event occurs. During idle periods (common case), periodic animations start but never advance frames, so the banner/logo appears frozen.
   - Evidence: `teleclaude/cli/tui/app.py:517-544` (render gated by events) and `teleclaude/cli/tui/app.py:887-897` (animation update only in `_render`).
   - **Why this matters:** Violates FR-1.1 (engine manages frame updates at a configurable FPS) and acceptance criteria for smooth animations.
   - **Fix:** Drive `_render` (or at least `animation_engine.update()`) from a fixed timer/tick loop; add a configurable FPS/interval and render on each tick regardless of input events.
   - **Confidence: 90**

## Important Issues

1. **No double-buffering to prevent flicker (FR-1.3).**
   - The engine mutates a single `_colors`/`_logo_colors` dict in place and the renderer reads from the same state; there is no frame buffer swap.
   - Evidence: `teleclaude/cli/tui/animation_engine.py:11-67`.
   - **Fix:** Maintain front/back buffers and swap after each update; render should read from a stable snapshot.
   - **Confidence: 85**

2. **No queue/priority handling for periodic vs activity animations (FR-1.4, FR-3.4).**
   - `AnimationEngine.play()` simply replaces the current animation, and triggers call `play()` directly with no queue or priority policy.
   - Evidence: `teleclaude/cli/tui/animation_engine.py:30-40`, `teleclaude/cli/tui/animation_triggers.py:31-39`, `teleclaude/cli/tui/animation_triggers.py:65-71`.
   - **Fix:** Add a queue with priority (activity > periodic), with explicit interruption rules and optional preemption.
   - **Confidence: 85**

3. **Per-animation speed/easing and configurable FPS are not implemented (FR-1.1, FR-2.4, FR-4.4).**
   - `Animation.speed_ms` is stored but not used to drive timing; the render cadence is fixed to `WS_POLL_INTERVAL_MS` and easing utilities are absent.
   - Evidence: `teleclaude/cli/tui/animations/base.py:15-33`, `teleclaude/cli/tui/app.py:512`, `teleclaude/cli/tui/app.py:887-897`.
   - **Fix:** Introduce an animation tick scheduler that respects per-animation speed or a configured FPS; add easing helpers and use them in animations that require transitions.
   - **Confidence: 82**

4. **Animation subset selection is missing from configuration (NFR-3).**
   - The UI config only includes `animations_enabled` and `animations_periodic_interval`; there is no way to select a subset of animations.
   - Evidence: `teleclaude/config.py:158-214`, `config.sample.yml:51-54`.
   - **Fix:** Add a configurable allowlist/denylist (e.g., `ui.animations_subset`) and filter the animation pools in triggers.
   - **Confidence: 82**

5. **Test coverage is far below requirements; integration test is still unchecked.**
   - Unit tests cover only pixel mapping, a single animation, and basic engine stop logic; there are no tests for triggers, animation completion clearing, small-vs-big behavior, or config disable. The integration test item remains unchecked in the implementation plan.
   - Evidence: `tests/unit/test_animations.py:13-60`, `todos/banner-animations/implementation-plan.md:324-334`.
   - **Fix:** Add unit tests for engine update/clear, triggers (periodic + activity), and small/big compatibility; add an integration test for render/trigger flow and mark the plan item complete.
   - **Confidence: 88**

## Fixes Applied

### Critical Issue #1: Steady render tick

- **Commit:** 08c0df8
- **Changes:** Modified main loop in `app.py` to call `_render()` on every iteration (~100ms), not just on key/WS events
- **Result:** Animations now advance during idle periods
- **Tests:** Passing

### Important Issue #1: Double-buffering

- **Commit:** ae75f13
- **Changes:** Added front/back buffer pairs (`_colors_front`/`_colors_back`, `_logo_colors_front`/`_logo_colors_back`) to `AnimationEngine`
- **Result:** Renderer reads from stable front buffer while animations update back buffer, then swap atomically
- **Tests:** Passing

### Important Issue #2: Queue/priority handling

- **Commit:** 3db9eff
- **Changes:**
  - Added `AnimationPriority` enum (PERIODIC=1, ACTIVITY=2)
  - Added priority queues (`_big_queue`, `_small_queue`) with maxlen=5
  - Updated `play()` to accept priority parameter and handle interruption/queueing
  - Activity animations interrupt periodic animations; same priority replaces current
- **Result:** Activity animations correctly interrupt periodic animations
- **Tests:** Passing (test_priority_queue)

### Important Issue #3: Per-animation speed timing

- **Commit:** 843e54d
- **Changes:**
  - Added `_big_last_update_ms` and `_small_last_update_ms` to track elapsed time
  - Modified `update()` to only advance frames when `elapsed_ms >= animation.speed_ms`
  - Animations can now run at different speeds (e.g., 50ms/frame vs 200ms/frame)
- **Result:** Per-animation `speed_ms` is now respected
- **Tests:** Passing (updated existing tests to account for timing)
- **Note:** Easing functions deferred - no current animations require them

### Important Issue #4: Animation subset configuration

- **Commit:** 2fd32b2
- **Changes:**
  - Added `animations_subset: List[str]` to `UIConfig`
  - Added `filter_animations()` helper function
  - Updated `PeriodicTrigger` and `ActivityTrigger` to filter by subset
  - Added to `config.sample.yml` with documentation
- **Result:** Users can filter animations by class name (empty list = all enabled)
- **Tests:** Passing (test*filter_animations*\*)

### Important Issue #5: Test coverage

- **Commit:** 24aa2e8
- **Changes:** Added comprehensive tests for:
  - Engine clear on completion
  - Priority queue behavior
  - Simultaneous big/small animations
  - Engine disabled state
  - Animation subset filtering (empty, by name, no match)
- **Result:** Test coverage now includes all core engine/trigger functionality
- **Tests:** 11 animation tests passing (was 3)
- **Note:** Integration test deferred - requires full TUI environment setup

## Verdict: REQUEST CHANGES

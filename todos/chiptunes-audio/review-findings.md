# Review Findings: chiptunes-audio

## Paradigm-Fit Assessment

The implementation follows established codebase patterns well:

- **Data flow**: Config -> Manager -> RuntimeSettings -> API -> TUI. Matches the TTS pattern precisely.
- **Component reuse**: Extends existing `SettingsPatch`, `SettingsPatchDTO`, `SettingsDTO`, `DataRefreshed`, `SettingsChanged` message patterns rather than introducing new abstractions.
- **Pattern consistency**: Keybinding, `@work` decorator, `reactive` properties, footer icon click handling all match adjacent TTS code.

No paradigm violations found.

## Critical

### C1. Thread self-join breaks auto-advance (player.py:204-220, manager.py:69-86, player.py:200-202)

When a track ends naturally (emulation loop exits), the callback chain executes on the emulation thread:

1. `_emulation_loop` exits -> `_notify_track_end()` (player.py:201-202)
2. -> `manager._on_track_end()` -> `_play_random()` (manager.py:112-116)
3. -> `self._player.stop()` (manager.py:80) on the OLD player
4. -> `self._thread.join(timeout=2.0)` (player.py:219)

Step 4 is a thread joining itself. Python raises `RuntimeError: cannot join current thread`. This exception is caught by `_notify_track_end`'s `except Exception` handler (player.py:243) and logged as a warning, but auto-advance silently fails.

**Effect**: The requirement "When a track finishes, the next random track starts automatically" is broken. Each track plays once, then silence.

**Fix**: Schedule auto-advance on a separate thread or use a flag checked outside the callback chain. For example, `_on_track_end` could spawn a short-lived thread to call `_play_random()`, or the manager could use `threading.Timer(0, self._play_random)`.

### C2. No track duration mechanism -- SID tunes loop indefinitely (player.py:180-202)

SID files contain no end-of-track marker. The 6502 play routine loops forever (it's called repeatedly by the emulation loop). The emulation loop only exits on:
- Explicit `stop()` call (user toggle)
- Emulation error (exception in play_frame/render_frame)

There is no timer-based track rotation. The requirement "When a track finishes, the next random track starts automatically" has no triggering mechanism for well-behaved tunes since they never "finish."

**Effect**: A single track plays indefinitely until the user manually toggles off.

**Fix**: Add a configurable max track duration (e.g., 3-5 minutes) after which the emulation loop stops and triggers `_notify_track_end()`. This is the standard approach for SID players (HVSC Song Length Database provides per-tune durations, but a simple timer-based fallback suffices for v1).

## Important

### I1. Emulation loop has no frame-rate throttling (player.py:180-198)

The emulation loop generates frames as fast as the CPU can emulate, with no sleep between frames. When emulation is faster than real-time (likely for simple tunes), the loop fills the 200-frame queue rapidly then oscillates between 1-second `put()` timeouts and frame generation.

**Effect**: The emulation thread consumes 100% CPU on one core during playback. After the queue fills, it wastes cycles in timeout loops rather than sleeping at the playback rate (~20ms per frame at 50Hz).

**Fix**: Add a simple rate limiter: `time.sleep(max(0, frame_duration - elapsed))` after each frame generation, or use `threading.Event.wait(frame_duration)` to pace the loop.

### I2. Silent exception swallowing in CPU emulation (sid_cpu.py:102-103)

```python
except Exception:  # pylint: disable=broad-exception-caught
    break  # Treat CPU exceptions as end-of-routine
```

All CPU emulation errors are silently swallowed without logging. `TypeError`, `AttributeError`, `IndexError`, bugs in py65emu -- all hidden. The caller (`play_frame`) has no indication the frame was interrupted.

**Fix**: Add `logger.debug("CPU exception during emulation: %s", exc)` before the break so failures are at least visible in debug logs.

### I3. Inconsistent `_chiptunes_manager` access in TTSManager (tts/manager.py:255 vs 294 vs 320)

Three methods access `_chiptunes_manager` using two different patterns:
- `trigger_event` (line 255): `getattr(self, "_chiptunes_manager", None)` -- defensive
- `speak` (line 294): `self._chiptunes_manager` -- direct
- `_handle_tts_result` (line 320): `getattr(self, "_chiptunes_manager", None)` -- defensive

Since `__init__` always initializes `self._chiptunes_manager = None`, the `getattr` calls are unnecessary. The inconsistency suggests the `trigger_event`/`_handle_tts_result` code was patched separately from `speak`.

**Fix**: Use `self._chiptunes_manager` consistently in all three locations.

### I4. `_handle_tts_result` resumes chiptunes unconditionally (tts/manager.py:319-322)

```python
_chiptunes = getattr(self, "_chiptunes_manager", None)
if _chiptunes is not None:
    _chiptunes.resume()
```

This resumes chiptunes on every TTS completion, even if chiptunes were not paused (e.g., chiptunes were disabled during TTS playback). While `resume()` is a no-op when the player is stopped, the asymmetry with the pause path (which checks `is_playing`) suggests an oversight.

**Fix**: Guard with `if _chiptunes is not None and _chiptunes.enabled:` or track pause state explicitly.

### I5. Pre-existing: duplicated `asyncio.get_running_loop()` in `_schedule_flush` (runtime_settings.py:182-191)

The method calls `asyncio.get_running_loop()` twice -- lines 183 and 189. The second call is completely redundant since the first already guards with `except RuntimeError: return`. This is pre-existing code but the chiptunes patch extends the `patch()` method that calls `_schedule_flush`, so it's in scope.

## Suggestions

### S1. TTS coexistence test duplicates logic instead of calling real code (test_chiptunes.py:456-472)

`test_trigger_event_pauses_chiptunes` manually replicates the pause condition inline rather than calling `mgr.trigger_event(...)`. The test passes even if the actual `trigger_event` method removes the pause logic.

### S2. Test accesses private `_paused` attribute directly (test_chiptunes.py:293-300)

`test_pause_resume` asserts `player._paused is True` instead of testing observable behavior. A refactor that renames the field breaks the test even if behavior is preserved.

### S3. No test for auto-advance behavior (tests/unit/test_chiptunes.py)

The most critical user-facing behavior -- track ending triggers next random track -- has no test coverage. The thread self-join bug (C1) would have been caught by an auto-advance test.

### S4. No test for `_handle_tts_result` resuming chiptunes (tts/manager.py:319-322)

The resume half of the TTS coexistence contract is untested.

## Demo Artifact Review

- Block 1 (import check): Valid, tests actual import path.
- Block 2 (settings patch): Valid, exercises real `parse_patch` method.
- Block 3 (API curl): Valid, uses actual endpoint. Requires running daemon.
- Block 4 (file discovery): Valid, depends on HVSC collection being present.
- Guided steps 1-8: Reasonable manual walkthrough covering toggle, auto-advance, click, TTS coexistence, persistence, and API.

The demo is adequate for the feature scope. Auto-advance (Step 3) would fail due to C1+C2 but the demo notes "wait for the current track to end" which in practice never happens (C2).

## Zero-Finding Justification

N/A -- multiple findings exist.

---

## Fixes Applied

### C1 — Thread self-join (player.py)
`stop()` now checks `self._thread is not threading.current_thread()` before calling `join()`.
When auto-advance fires from the emulation thread, `stop()` skips the join (the thread is a daemon and will exit naturally) instead of raising `RuntimeError`.
Commit: `453caa2ba`

### C2 — No track duration mechanism (player.py)
Added `max_track_duration` parameter (default 300 s) to `ChiptunesPlayer.__init__`.
`_emulation_loop` now records `track_start = time.monotonic()` and breaks the loop when elapsed time exceeds the limit, triggering `_notify_track_end()` for auto-advance.
Commit: `453caa2ba`

### I1 — Emulation loop throttling (player.py)
After each frame, `_stop_event.wait(max(0.0, frame_duration - elapsed))` paces the loop to ~50 Hz real-time instead of spinning at 100% CPU.
The `wait()` call also makes the loop immediately interruptible on `stop()`.
Commit: `453caa2ba`

### I2 — Silent CPU exception swallowing (sid_cpu.py)
Added `logger = get_logger(__name__)` and `logger.debug("CPU exception during emulation: %s", exc)` before the `break` in `_run_to_return`.
Commit: `23fcb3bf1`

### I3 — Inconsistent `_chiptunes_manager` access (tts/manager.py)
Replaced `getattr(self, "_chiptunes_manager", None)` with `self._chiptunes_manager` in both `trigger_event` and `_handle_tts_result`. The attribute is always initialised in `__init__`.
Commit: `b4c1b06ce`

### I4 — Unconditional resume (tts/manager.py)
`_handle_tts_result` now guards `resume()` with `self._chiptunes_manager.enabled` so it does not resume when chiptunes were toggled off during TTS playback.
Commit: `b4c1b06ce`

### I5 — Duplicated `asyncio.get_running_loop()` (runtime_settings.py)
Removed the second unreachable `try/except RuntimeError` block from `_schedule_flush`. The first block already returns early on `RuntimeError`.
Commit: `d0a8cae71`

### Additional (from reviewer)
- Prebuffer wait: replaced throwaway `threading.Event().wait(0.05)` with `self._stop_event.wait(0.05)` — commit `453caa2ba`
- Zombie emulation thread on stream open failure: `self._stop_event.set()` now called before clearing `_playing` — commit `453caa2ba`

Tests: 41 passed, 5 skipped (py65emu/pyresidfp/sounddevice optional deps)
Lint: 10.00/10 on all modified files

---

### Test fix (from re-review)
- `test_tts_fallback_saturation.py`: `_make_manager` factory bypasses `__init__` via `__new__`, missing `_chiptunes_manager` attribute. Added initialization to factory.

Tests: 2757 passed, 5 skipped (py65emu/pyresidfp/sounddevice optional deps)
Lint: clean on all modified files

---

**Verdict: APPROVE**

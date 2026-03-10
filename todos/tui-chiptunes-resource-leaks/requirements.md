# tui-chiptunes-resource-leaks — Requirements

## Context

Three resource-leak and reliability fixes for the chiptunes playback system, targeting a
terminal freeze that occurs after 1–2 hours of continuous playback. [inferred: all three
production fixes have already landed in `main` via commit `e965ed810`; the remaining
deliverable for this todo is dedicated regression coverage for the three bug-fix paths.]

---

## R1 — Prune `_last_output_summary` on session removal

**Source:** `teleclaude/cli/tui/views/sessions.py` — `update_data()` (lines 165–168)

**Problem:** `SessionsView._last_output_summary` grew unboundedly as sessions came and went.
Each API poll call added entries for new sessions but never removed entries for dead ones.
At scale or over time this dict grew large enough to measurably slow the state serialization
path (`get_persisted_state`), which runs on the Textual event loop.

**Required behavior:**
- When a session ID disappears from the latest `update_data()` payload, its entry is removed
  from `_last_output_summary` during the same update cycle.
- Summary entries for session IDs that remain present are preserved unchanged.
- No additional warning or operator-visible cleanup signal is required.

**Success criteria:**
- Unit test: call `update_data()` with a session list that omits a session ID previously
  stored in `_last_output_summary`. Assert the stale key is absent after the call.
- Unit test: call `update_data()` with a session list that retains an existing summary entry.
  Assert the retained entry is untouched.

---

## R2 — Call `stop()` on failed stream reopen in `resume()`

**Source:** `teleclaude/chiptunes/player.py` — `resume()` method (lines 312–331)

**Problem:** When `_open_stream()` fails during `resume()`, the original code returned early
without calling `stop()`. The emulation thread was still alive (blocked on `_resume_event`),
the `_paused` flag was cleared (making `is_playing` return `True`), and `_stop_event` was
never set. This left the emulation thread in a zombie spin loop on
`_resume_event.wait(timeout=0.1)` indefinitely.

**Required behavior:**
- If `resume()` must reopen the audio stream and that reopen fails, the player transitions to
  a fully stopped state instead of remaining in a paused-but-reporting-playing limbo.
- The failure path emits one warning-level diagnostic indicating that resume failed and the
  track is being stopped.
- Cleanup leaves the emulation thread unblocked and the player reporting `is_playing == False`.

**Success criteria:**
- Unit test: player with `_playing=True`, `_paused=True`, `_stream=None`,
  `_stream_blocksize=256`; `_open_stream` patched to return `False`. Call `resume()`.
  Assert: `is_playing` is `False`, `_stop_event.is_set()` is `True`,
  `_resume_event.is_set()` is `True`, and one warning is emitted.
- Unit test: same setup but `_open_stream` returns `True`. Call `resume()`. Assert
  `is_playing` is `True`, `_paused` is `False`, `_resume_event.is_set()` is `True`, and the
  failure warning is not emitted.

---

## R3 — Log warning on emulation thread join timeout in `stop()`

**Source:** `teleclaude/chiptunes/player.py` — `stop()` method (lines 280–294)

**Problem:** `stop()` joined the emulation thread with a 2-second timeout but silently
discarded the alive-check result. An orphaned thread left no trace in logs, making
freeze debugging impossible.

**Required behavior:**
- If the emulation thread is still alive after `stop()` waits for its bounded join timeout,
  emit one warning-level diagnostic that the thread did not exit cleanly.
- If the emulation thread exits within the timeout, `stop()` does not emit that orphaned-thread
  warning.
- The thread remains `daemon=True`; the warning is observability only and does not require an
  extra recovery path.

**Success criteria:**
- Unit test: player with a live emulation thread that ignores `_stop_event`. Call `stop()`.
  Assert `logger.warning` is called with a message matching `"orphaned"`.
- Unit test: player with an emulation thread that exits within the timeout. Call `stop()`.
  Assert no orphaned-thread warning is emitted.

---

## Out of scope

- WS broadcast dedup
- Animation buffer leaks
- Audio sidecar resource management

---

## Definition of Done alignment

### Testing (Section 3)
- Tests added in `tests/unit/test_chiptunes.py` (R2, R3) and a sessions-view unit test
  module for R1. [inferred: existing test file organization]
- Each fix has at minimum: one test for the failure/cleanup path and one for the
  non-error/happy path.

### Documentation (Section 6)
- No CLI surface, config keys, or wizard changes required.
- `logger.warning` messages serve as the operational record.

### Observability (Section 8)
- R3 adds one new `warning`-level log line in `stop()`. No structural log changes.

---

## Implementation status [inferred]

All three code fixes are present in `main` as of commit `e965ed810`. The builder's scope
is test coverage only — do not re-implement the fixes.

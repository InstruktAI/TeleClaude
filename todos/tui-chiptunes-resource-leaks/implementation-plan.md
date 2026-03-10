# tui-chiptunes-resource-leaks — Implementation Plan

## Atomicity verdict

**Atomic — proceed.** All three production fixes are already in `main` (commit `e965ed810`).
Builder scope is test coverage only: two test locations, no architectural decisions, one new
test file. Work is a single coherent behavior (regression coverage for three bug-fix paths).
Do not split.

---

## Grounding summary

| Requirement | Fix location | Status |
|---|---|---|
| R1 — prune `_last_output_summary` | `teleclaude/cli/tui/views/sessions.py:165–168` | In code ✓ |
| R2 — call `stop()` on failed reopen | `teleclaude/chiptunes/player.py:324–328` | In code ✓ |
| R3 — warn on thread join timeout | `teleclaude/chiptunes/player.py:292–293` | In code ✓ |

---

## Task 1 — R2 & R3: player resource-leak regression tests

**File:** `tests/unit/test_chiptunes.py` (append new class)

### Why here

`test_chiptunes.py` already contains `TestChiptunesPlayerLifecycle` which tests `stop()`,
`pause()`, and `resume()` at unit scope using the same constructor pattern. Adding the new
tests to the same file keeps player coverage co-located.

### R2 — failure path: `test_resume_failed_reopen_stops_player`

**Setup:**
- `ChiptunesPlayer()` — no sounddevice needed; we don't call `play()`.
- Set `player._playing = True`, `player._paused = True`, `player._stream = None`,
  `player._stream_blocksize = 256`.
- Patch `player._open_stream` via `monkeypatch.setattr` to return `False`.
- Capture `logger.warning` via `unittest.mock.patch("teleclaude.chiptunes.player.logger.warning")`.

**Call:** `player.resume()`

**Assert:**
- `player.is_playing is False`
- `player._stop_event.is_set() is True`
- `player._resume_event.is_set() is True`
- `mock_warning` called at least once with an arg containing `"Failed to reopen"`.

**Why:** confirms `stop()` is called on failed reopen; emulation thread cannot enter zombie loop.

### R2 — success path: `test_resume_successful_reopen_plays`

**Setup:** same, but `_open_stream` patched to return `True`.

**Call:** `player.resume()`

**Assert:**
- `player.is_playing is True`
- `player._paused is False`
- `player._resume_event.is_set() is True`
- No `mock_warning` call contains `"Failed to reopen"`.

**Why:** guards against regression that calls `stop()` even on successful reopen.

### R3 — orphan path: `test_stop_logs_warning_when_thread_does_not_exit`

**Setup:**
- `ChiptunesPlayer()`.
- Create `threading.Thread(target=<function blocking on a never-set Event>, daemon=True)`,
  start it, assign to `player._thread`.
- Patch `"teleclaude.chiptunes.player.logger.warning"`.

**Call:** `player.stop()`

**Assert:**
- At least one `mock_warning` call has an arg matching `"orphaned"`.

**Implementation note:** the blocking function spins on `threading.Event().wait()` with the
event never set. `stop()` joins with a 2s timeout; the test asserts after `stop()` returns.
Do not manually join the thread in the test — `stop()` sets `_thread = None` regardless.

**Why:** confirms the observability fix is present for freeze diagnostics.

### R3 — clean exit path: `test_stop_does_not_warn_when_thread_exits_cleanly`

**Setup:**
- `ChiptunesPlayer()`.
- Create `threading.Thread(target=lambda: None, daemon=True)`, start it, join it to ensure
  it exits, then assign to `player._thread`.
- Patch `"teleclaude.chiptunes.player.logger.warning"`.

**Call:** `player.stop()`

**Assert:**
- No `mock_warning` call arg contains `"orphaned"`.

**Why:** guards against false positives.

### Verification

```bash
pytest tests/unit/test_chiptunes.py::TestChiptunesPlayerResourceLeaks -v
```

All four tests must be green. No lint/type errors.

---

## Task 2 — R1: sessions-view output-summary pruning tests

**File:** `tests/unit/test_sessions_view_output_summary.py` (new)

### Why new file

R1 tests target `SessionsView._last_output_summary` via `update_data()`. The two existing
sessions-view files cover `action_toggle_preview` and `toggle_project`; pruning is a
distinct concern that deserves its own module.

### Harness pattern

`SessionsView` is a Textual `Widget`. Constructing it outside a running app works (the
existing sticky/preview tests confirm this). However, `update_data()` calls `_rebuild_tree()`
when session IDs change, which touches DOM internals. Monkeypatch both `_rebuild_tree` and
`post_message` to no-ops before calling `update_data()`.

**Helper:**
```python
def _make_session(session_id: str):
    from teleclaude.cli.models import SessionInfo
    return SessionInfo(session_id=session_id, title="t", status="active")
```

### `test_update_data_prunes_stale_output_summary`

**Setup:**
- `view = SessionsView()`; monkeypatch `_rebuild_tree` and `post_message` to `lambda *a, **k: None`.
- `view._last_output_summary["gone-id"] = {"text": "old", "ts": 0.0}`
- `view._last_output_summary["keep-id"] = {"text": "kept", "ts": 1.0}`

**Call:** `view.update_data(computers=[], projects=[], sessions=[_make_session("keep-id")])`

**Assert:**
- `"gone-id" not in view._last_output_summary`
- `"keep-id" in view._last_output_summary`
- `view._last_output_summary["keep-id"]["text"] == "kept"` (entry untouched)

### `test_update_data_preserves_retained_output_summary`

**Setup:**
- `view = SessionsView()`; monkeypatch `_rebuild_tree` and `post_message`.
- `view._last_output_summary["sess-a"] = {"text": "summary-a", "ts": 5.0}`

**Call:** `view.update_data(computers=[], projects=[], sessions=[_make_session("sess-a")])`

**Assert:**
- `"sess-a" in view._last_output_summary`
- `view._last_output_summary["sess-a"]["text"] == "summary-a"`

### Verification

```bash
pytest tests/unit/test_sessions_view_output_summary.py -v
```

Both tests must be green. No lint/type errors.

---

## Task 3 — Demo artifact alignment

**File:** `todos/tui-chiptunes-resource-leaks/demo.md`

### Why here

Code review always checks `demo.md`. Even though builder scope is regression coverage only, the
demo still needs to show the exact validation commands and the expected green outcomes for R1–R3.

### Update

- Keep the demo focused on the two targeted `pytest` commands from Tasks 1 and 2.
- Ensure the guided presentation states the concrete expectations:
  - four green player tests for R2/R3
  - two green sessions-view tests for R1
- Do not add fabricated output or unrelated commands.

### Verification

`todos/tui-chiptunes-resource-leaks/demo.md` contains only the targeted pytest commands and
describes the expected passing observations for R1, R2, and R3.

---

## Task 4 — Commit

After Tasks 1, 2, and 3 are complete and `make lint` passes:

- Stage only the files that belong to this todo.
- Inspect `git diff --staged` before committing.
- Commit and let the pre-commit hooks run.
- Push `origin main` immediately after the commit (canonical `main` worktree policy).

Commit message:

```
test(chiptunes): add regression coverage for resource-leak fixes

R1: _last_output_summary pruned on session removal (sessions.py)
R2: stop() called on failed stream reopen in resume() (player.py)
R3: warning logged on emulation thread join timeout in stop() (player.py)

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```

---

## Review anticipation

| Req | Test | Reviewer expectation |
|---|---|---|
| R1 stale | `test_update_data_prunes_stale_output_summary` | stale key removed |
| R1 retain | `test_update_data_preserves_retained_output_summary` | retained entry unchanged |
| R2 failure | `test_resume_failed_reopen_stops_player` | is_playing=F, events set, warning |
| R2 success | `test_resume_successful_reopen_plays` | is_playing=T, no failure warning |
| R3 orphan | `test_stop_logs_warning_when_thread_does_not_exit` | "orphaned" in warning |
| R3 clean | `test_stop_does_not_warn_when_thread_exits_cleanly` | no orphan warning |
| Demo | `todos/tui-chiptunes-resource-leaks/demo.md` | exact pytest commands, no fabricated behavior |

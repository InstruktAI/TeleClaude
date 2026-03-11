# Implementation Plan: session-polling-baseline

## Atomicity decision

**ATOMIC — proceed.** All five requirements are small, well-bounded, and share one
coherent workstream (baseline corrections + corpus). No independent shippability
benefit from splitting; coordination cost would exceed session-size savings.

---

## Tasks

Each R1–R3 section follows TDD policy: RED test first, then GREEN production code.
R4/R5 are test artifacts — fixtures first, then replay tests.

---

### T1 · R1 RED — Failing test: capture_pane default line count

**File:** `tests/unit/test_tmux_bridge.py`

Add `test_capture_pane_default_uses_lookback_constant`:

- Patch `asyncio.create_subprocess_exec` to capture the command args.
- Call `await tmux_bridge.capture_pane("tc_test")` without `capture_lines`.
- Assert the command list contains `"-S"` followed by `"-500"` (not `"-3900"`).
- The test must **fail** before T2 because `CAPTURE_PANE_LOOKBACK_LINES` doesn't
  exist yet.

**Why:** Tests-first prevents regressing back to the 3900-char misuse after any
future refactor touches this function.

**Verification:** `pytest tests/unit/test_tmux_bridge.py::test_capture_pane_default_uses_lookback_constant` fails with assertion error on `-3900`.

---

### T2 · R1 GREEN — Add constant and fix capture_pane fallback

**Files:** `teleclaude/constants.py`, `teleclaude/core/tmux_bridge.py`

1. **`teleclaude/constants.py`** (after line 30, in the "Internal configuration" block):
   ```python
   CAPTURE_PANE_LOOKBACK_LINES = 500  # Default tmux scrollback line count for capture_pane()
   ```

2. **`teleclaude/core/tmux_bridge.py`**:
   - Add `CAPTURE_PANE_LOOKBACK_LINES` to the import from `teleclaude.constants`
     (line 24 already imports `UI_MESSAGE_MAX_CHARS`).
   - Line 1030: change the fallback expression to:
     ```python
     window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else CAPTURE_PANE_LOOKBACK_LINES
     ```
   - Add an inline comment: `# capture_lines is a line count, not a char budget`

**Why:** `UI_MESSAGE_MAX_CHARS = 3900` is a UI char budget. Passing it as `-S -3900`
to tmux means 3900 lines of scrollback per capture — 7× more than needed. This
inflates every capture subprocess call with unnecessary scrollback data.

**Verification:** T1 test passes. `grep "UI_MESSAGE_MAX_CHARS" teleclaude/core/tmux_bridge.py` returns no results. No explicit-`capture_lines` callers affected.

---

### T3 · R2 RED — Failing tests for tmp dir cleanup

**File:** `tests/unit/test_session_cleanup.py`, `tests/unit/test_tmux_bridge_tmpdir.py`

**In `test_session_cleanup.py`**, add (fail at import — `cleanup_orphan_tmp_dirs` absent):

```
test_cleanup_session_resources_removes_tmp_dir
```
- Build a mock session with a known `session_id`.
- Patch `tmux_bridge.get_session_tmp_basedir` → returns a tmp_path-based Path.
- Patch `tmux_bridge.safe_path_component` → returns `"safe_id"`.
- Create `tmp_base / "safe_id"` directory.
- Call `cleanup_session_resources(session, mock_adapter_client)`.
- Assert the directory no longer exists.

```
test_cleanup_orphan_tmp_dirs_removes_unknown_dirs_and_returns_count
```
- Create `tmp_base` with two dirs: one matching a known session's safe component, one unknown.
- Patch `tmux_bridge.get_session_tmp_basedir` → `tmp_base`.
- Patch `tmux_bridge.safe_path_component` identity.
- Patch `db.get_all_sessions` → one session matching the known dir.
- Call `await cleanup_orphan_tmp_dirs()`.
- Assert return value is `1`; unknown dir removed, known dir intact.

**In `test_tmux_bridge_tmpdir.py`**, add:

```
test_public_helpers_are_accessible_on_module
```
- `from teleclaude.core.tmux_bridge import get_session_tmp_basedir, safe_path_component`
- Assert both are callable. Fails before T4.

**Verification:** All three tests fail with `ImportError` or `AttributeError`.

---

### T4 · R2a GREEN — Rename private helpers to public in tmux_bridge

**File:** `teleclaude/core/tmux_bridge.py`

1. Rename `_get_session_tmp_basedir` → `get_session_tmp_basedir` (line 168).
2. Rename `_safe_path_component` → `safe_path_component` (line 175).
3. Add both names to `__all__` (lines 29–50):
   ```python
   "get_session_tmp_basedir",
   "safe_path_component",
   ```
4. Update `_prepare_session_tmp_dir` (line 182–191) to use public names:
   ```python
   safe_id = safe_path_component(session_id)
   base_dir = get_session_tmp_basedir()
   ```

**Why:** `session_cleanup` needs to call these helpers without accessing private names
across module boundaries. Public + `__all__` signals stable API intent and satisfies
the import test.

**Verification:** `test_public_helpers_are_accessible_on_module` passes. All existing
`test_tmux_bridge_tmpdir.py` tests remain green.

---

### T5 · R2b GREEN — Teardown tmp cleanup in cleanup_session_resources()

**File:** `teleclaude/core/session_cleanup.py`

After the workspace dir removal block (after line ~99), add:

```python
# Clean up per-session tmp directory (created by _prepare_session_tmp_dir in tmux_bridge)
safe_id = tmux_bridge.safe_path_component(session_id)
session_tmp_dir = tmux_bridge.get_session_tmp_basedir() / safe_id
if session_tmp_dir.exists():
    try:
        await asyncio.to_thread(shutil.rmtree, session_tmp_dir)
        logger.debug("Deleted tmp directory for session %s", session_id[:8])
    except Exception as e:
        logger.warning("Failed to delete tmp dir for session %s: %s", session_id[:8], e)
```

`shutil` (line 15) and `asyncio` (line 13) are already imported.

**Why:** Teardown only removes the workspace dir today, leaving tmp dirs to accumulate
indefinitely. Best-effort (non-fatal) matches the workspace removal pattern above.

**Verification:** `test_cleanup_session_resources_removes_tmp_dir` passes.

---

### T6 · R2c GREEN — Add cleanup_orphan_tmp_dirs() and wire into periodic_cleanup

**File:** `teleclaude/core/session_cleanup.py`, `teleclaude/services/maintenance_service.py`

**In `session_cleanup.py`**, add after `cleanup_orphan_workspaces()`:

```python
async def cleanup_orphan_tmp_dirs() -> int:
    """Remove per-session tmp dirs that have no corresponding DB entry.

    Follows the cleanup_orphan_workspaces() pattern.

    Returns:
        Number of orphan tmp directories removed.
    """
    base_dir = tmux_bridge.get_session_tmp_basedir()
    if not base_dir.exists():
        logger.debug("Session tmp base directory does not exist")
        return 0

    all_sessions = await db.get_all_sessions()
    known_safe_ids = {tmux_bridge.safe_path_component(s.session_id) for s in all_sessions}

    removed_count = 0
    for tmp_dir in base_dir.iterdir():
        if not tmp_dir.is_dir():
            continue
        if tmp_dir.name not in known_safe_ids:
            logger.warning("Found orphan session tmp dir: %s (not in DB), removing", tmp_dir.name)
            try:
                shutil.rmtree(tmp_dir)
                removed_count += 1
                logger.info("Removed orphan session tmp dir: %s", tmp_dir.name)
            except Exception as e:
                logger.error("Failed to remove orphan session tmp dir %s: %s", tmp_dir.name, e)

    if removed_count > 0:
        logger.info("Removed %d orphan session tmp directories", removed_count)

    return removed_count
```

**In `maintenance_service.py`**, add after line 62 (`cleanup_orphan_workspaces()`):

```python
await session_cleanup.cleanup_orphan_tmp_dirs()
```

**Why:** Mirrors the workspace orphan sweep exactly. Catches sessions that were
force-killed or otherwise bypassed teardown.

**Verification:** `test_cleanup_orphan_tmp_dirs_removes_unknown_dirs_and_returns_count`
passes. `grep "cleanup_orphan_tmp_dirs" teleclaude/services/maintenance_service.py`
returns one match.

---

### T7 · R3 RED — Failing tests for OutputPoller changes

**File:** `tests/unit/test_output_poller.py`

Add two new tests (fail because current code calls `session_exists` every tick):

```
test_process_exited_on_empty_capture_and_session_exists_never_called
```
- `capture_pane` returns: `["hello", "hello world", ""]`.
- `session_exists` patched as `AsyncMock` — assert call count is 0 after run.
- `is_pane_dead` returns `False`.
- `db.get_session` returns session with `closed_at=None`, `lifecycle_status="active"`.
- Collect events; assert `ProcessExited` is yielded.
- Assert `session_exists.call_count == 0`.

```
test_is_pane_dead_called_at_most_every_5_iterations
```
- `capture_pane` returns 12 non-empty strings then `""`.
- `is_pane_dead` patched as `AsyncMock(return_value=False)`.
- `session_exists` must not be called.
- Collect events until ProcessExited.
- Assert `is_pane_dead.call_count == 2` so the cadence is proven to be exactly
  iterations 5 and 10 before the empty-capture exit on iteration 13.

**Verification:** Both tests fail because the current code calls `session_exists`
on every iteration.

---

### T8 · R3 GREEN — Remove per-tick session_exists, throttle is_pane_dead

**File:** `teleclaude/core/output_poller.py`

**Remove:**
- Line 94: `session_existed_last_poll = True` initialization (verify unused after changes).
- Line 138: `session_exists_now = await tmux_bridge.session_exists(...)`.
- Lines 141–173: the watchdog block (`if session_existed_last_poll and not session_exists_now:`).
- Line 174: `if not session_exists_now:` exit block (through `break` on line 195).
- Line 197: `session_existed_last_poll = session_exists_now`.

**Reorder capture_pane:** Make `captured_output = await tmux_bridge.capture_pane(tmux_session_name)` the **first** statement inside the loop body.

**Add empty-capture exit block** immediately after `capture_pane()`:

```python
if not captured_output:
    if previous_output:
        # Had output before → session died; distinguish expected vs unexpected.
        try:
            session = await db.get_session(session_id)
        except RuntimeError:
            session = None
        if not session:
            logger.debug(
                "Session %s disappeared (session terminated) session=%s",
                tmux_session_name,
                session_id[:8],
            )
        elif session.closed_at or session.lifecycle_status in _TERMINAL_SESSION_STATUSES:
            logger.info(
                "Session %s disappeared during close transition "
                "(watchdog close race) session=%s status=%s",
                tmux_session_name,
                session_id[:8],
                session.lifecycle_status,
            )
        else:
            age_seconds = time.time() - started_at
            logger.critical(
                "Session %s disappeared between polls (watchdog triggered) "
                "session=%s age=%.2fs poll_iteration=%d seconds_since_last_poll=%.1f",
                tmux_session_name,
                session_id[:8],
                age_seconds,
                poll_iteration,
                poll_interval,
            )
    if previous_output and previous_output != last_sent_output and previous_output.strip():
        yield OutputChanged(
            session_id=session_id,
            output=previous_output,
            started_at=started_at,
            last_changed_at=last_output_changed_at,
        )
        last_sent_output = previous_output
    logger.info("Process exited for %s, stopping poll", session_id[:8])
    yield ProcessExited(
        session_id=session_id,
        exit_code=None,
        final_output=previous_output,
        started_at=started_at,
    )
    break
```

**Throttle is_pane_dead** (currently line ~280): change to:

```python
if poll_iteration % 5 == 0 and await tmux_bridge.is_pane_dead(tmux_session_name):
```

**Why:** `session_exists()` is redundant: an empty `capture_pane()` return already
signals session death. Removing it eliminates one async subprocess call per tick.
The watchdog logic is preserved — triggered by empty capture instead. `is_pane_dead()`
at 1/5 cadence is sufficient since the primary exit path handles most cases.

**Verification:**
- T7 tests pass.
- All existing `test_output_poller.py` tests remain green (update assertions that were coupled to `session_exists` mock call counts).
- `grep -n "session_exists" teleclaude/core/output_poller.py` returns no results.

---

### T9 · R4 — Create Codex pane snapshot fixture corpus

**Directory:** `tests/fixtures/codex_pane_snapshots/`

Create directory and 8 fixture files. ANSI sequences used:
- `\x1b[2m` = dim (SGR 2) — used for agent marker prefix
- `\x1b[1m` / `\x1b[0;1m` = bold (SGR 1) — required by `_ANSI_BOLD_TOKEN_RE`
- `\x1b[0m` = reset
- `›` (U+203A) = `CODEX_PROMPT_MARKER`
- `•` (U+2022) = agent marker (from `CODEX_AGENT_MARKERS`)

The `_ANSI_BOLD_TOKEN_RE` pattern is:
`\x1b\[[0-9;]*1m([A-Za-z][A-Za-z_-]{1,40})\x1b\[[0-9;]*m`
— bold token requires `\x1b[1m` prefix before the action word and `\x1b[0m` after.

**Fixture contents:**

`startup_prompt.txt` — fresh session, prompt at bottom, no history:
```
Welcome to Codex
Type your message below.

\x1b[1m›\x1b[0m
```

`typing_partial.txt` — prompt with partial input text:
```
Welcome to Codex

\x1b[1m›\x1b[0m implement the login feature
```

`spinner_active.txt` — agent spinner active, no prompt:
```
› fix the auth bug

\x1b[2m•\x1b[0m working...
```

`tool_action_read.txt` — Read tool in progress, no prompt:
```
› show me the config file

\x1b[2m•\x1b[0m \x1b[1mRead\x1b[0m teleclaude/config/__init__.py
```

`tool_done_prompt.txt` — tool done, live prompt returned:
```
› show me the config file

\x1b[2m•\x1b[0m \x1b[1mRead\x1b[0m teleclaude/config/__init__.py
Here is the content of the file...

\x1b[1m›\x1b[0m
```

`compact_fast_turn.txt` — compact dimmed agent boundary (fast turn):
```
› what is 2+2?

\x1b[2m•\x1b[0m 4
```

`stale_scrollback.txt` — old spinner markers in scrollback, live prompt at bottom:
```
\x1b[1m›\x1b[0m previous question

\x1b[2m•\x1b[0m working...
\x1b[2m•\x1b[0m planning...

\x1b[1m›\x1b[0m current question
```
(Spinner words "working" / "planning" are NOT in `_CODEX_TOOL_ACTION_WORDS`, no bold ANSI token → `_find_recent_tool_action` returns None.)

`seeded_prompt.txt` — prompt with pre-seeded long input:
```
\x1b[1m›\x1b[0m implement the full authentication flow with JWT tokens and refresh token rotation
```

**Why:** Synthetic content only — no real user data. ANSI codes reproduce the exact
parser branch conditions each test must exercise.

**Verification:**
- `ls tests/fixtures/codex_pane_snapshots/ | wc -l` = 8.
- Each file non-empty, parses as UTF-8, contains at least one `\x1b[` sequence.

---

### T10 · R5 — Create parser replay tests

**File:** `tests/unit/test_codex_replay.py` (new)

```python
"""Replay tests: feed Codex pane snapshot fixtures through the semantic parser.

These tests are the regression guard for the subsequent runtime extraction refactor.
They pass against current polling_coordinator.py and must remain green throughout.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from teleclaude.core.polling_coordinator import (
    _extract_prompt_block,
    _find_recent_tool_action,
    _has_live_prompt_marker,
    _is_compact_dimmed_agent_boundary_line,
    _is_live_agent_marker_line,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "codex_pane_snapshots"


def _load(name: str) -> str:
    return (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8")
```

**Test functions:**

1. `test_startup_prompt`:
   - `_has_live_prompt_marker(_load("startup_prompt"))` → True
   - `_find_recent_tool_action(_load("startup_prompt"))` → None

2. `test_typing_partial`:
   - `_has_live_prompt_marker(text)` → True
   - `_extract_prompt_block(text)[0]` is non-empty (contains "login")

3. `test_spinner_active`:
   - `_has_live_prompt_marker(text)` → False
   - Find last line starting with agent marker; `_is_live_agent_marker_line(line)` → True

4. `test_tool_action_read`:
   - `result = _find_recent_tool_action(text)` → non-None
   - `result[0] == "Read"`
   - `_has_live_prompt_marker(text)` → False

5. `test_tool_done_prompt`:
   - `_has_live_prompt_marker(text)` → True

6. `test_compact_fast_turn`:
   - Find the compact dimmed line (`•` with dim prefix)
   - `_is_compact_dimmed_agent_boundary_line(line)` → True

7. `test_stale_scrollback`:
   - `_has_live_prompt_marker(text)` → True
   - `_find_recent_tool_action(text)` → None

8. `test_seeded_prompt`:
   - `_has_live_prompt_marker(text)` → True
   - `prompt_text, _ = _extract_prompt_block(text)` → non-empty, contains "JWT"

**Why:** These 8 functions form the semantic parity baseline. Any change to the
parser helpers that breaks semantic behaviour will surface immediately here.

**Verification:**
- `pytest tests/unit/test_codex_replay.py -v` passes with 8 functions, < 1s.
- No mocking, no tmux/DB I/O.

---

### T11 · Demo artifact — Keep `demo.md` aligned with delivered checks

**File:** `todos/session-polling-baseline/demo.md`

- Update the validation blocks if any file paths, test entry points, or command
  names change while implementing T1–T10.
- Keep the demo executable with repo-local commands only; no placeholder output
  or speculative claims.
- Validate the artifact once with:
  ```bash
  telec todo demo validate session-polling-baseline
  ```

**Why:** The review lane checks `demo.md` on every todo. Keeping it synchronized in
the plan prevents a later review failure caused by stale validation steps after the
code/tests change.

**Verification:** `telec todo demo validate session-polling-baseline` exits 0 after
the implementation updates are complete.

---

## Review lane coverage

| Requirement | Test coverage | File |
|-------------|---------------|------|
| R1 constant | `test_capture_pane_default_uses_lookback_constant` | `test_tmux_bridge.py` |
| R2 helpers  | `test_public_helpers_are_accessible_on_module` | `test_tmux_bridge_tmpdir.py` |
| R2 cleanup  | `test_cleanup_session_resources_removes_tmp_dir` | `test_session_cleanup.py` |
| R2 orphan   | `test_cleanup_orphan_tmp_dirs_removes_unknown_dirs_and_returns_count` | `test_session_cleanup.py` |
| R3 no-exists | `test_process_exited_on_empty_capture_and_session_exists_never_called` | `test_output_poller.py` |
| R3 throttle | `test_is_pane_dead_called_at_most_every_5_iterations` | `test_output_poller.py` |
| R4 corpus   | loaded by replay tests | `tests/fixtures/codex_pane_snapshots/` |
| R5 replay   | 8 functions, one per fixture state | `test_codex_replay.py` |

Demo artifact coverage: T11 keeps `todos/session-polling-baseline/demo.md` executable
and in sync with the implementation.

No CLI changes, no config surface → DoD §6 wizard/sample gate auto-satisfied.

---

## Referenced paths

- `teleclaude/constants.py`
- `teleclaude/core/tmux_bridge.py`
- `teleclaude/core/session_cleanup.py`
- `teleclaude/services/maintenance_service.py`
- `teleclaude/core/output_poller.py`
- `teleclaude/core/polling_coordinator.py`
- `tests/unit/test_tmux_bridge.py`
- `tests/unit/test_tmux_bridge_tmpdir.py`
- `tests/unit/test_session_cleanup.py`
- `tests/unit/test_output_poller.py`
- `tests/unit/test_codex_replay.py` (new)
- `tests/fixtures/codex_pane_snapshots/` (new dir + 8 files)
- `todos/session-polling-baseline/demo.md`

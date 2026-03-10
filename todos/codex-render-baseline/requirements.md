# Requirements: codex-render-baseline

Split from parent `codex-render-semantic-runtime` — Phase 1 (Immediate Corrections)
and Phase 2 (Replay Corpus and Semantic Baseline).

## Goal

Deliver five independently shippable corrections and corpus artifacts that provide
immediate operational improvements (reduced subprocess overhead, proper tmp cleanup,
correct tmux lookback budget) and establish the semantic safety net that the core
runtime refactor (parent todo) depends on.

## In Scope

1. Separate the tmux capture-pane line lookback budget from the UI char budget.
2. Remove per-session tmp directory accumulation on session teardown and add orphan
   sweep.
3. Remove the redundant per-tick `session_exists()` subprocess call from the output
   poller hot loop.
4. Create a synthetic Codex pane snapshot fixture corpus (8 states) with ANSI codes
   intact.
5. Write parser replay tests that feed each fixture through the existing Codex
   semantic parser and assert the correct semantic output. These tests are the
   regression guard for the subsequent extraction refactor.

## Out of Scope

- Codex semantic runtime extraction / refactor (parent todo).
- Changes to how `capture_pane()` results are processed downstream of the function.
- New agent parsers, new semantic events, or changes to existing event schemas.
- Changes to the TUI or adapters.

## Cross-Cutting Verification

- Pre-commit hooks pass for the resulting change set.
- Existing affected unit coverage remains green alongside the new tests added in
  this todo.
- Verification demonstrates no behavioral regressions in the touched capture,
  cleanup, polling, and parser paths.

---

## R1 — Separate capture-pane line budget from char budget

### Problem

`tmux_bridge.capture_pane()` (line 1030) falls back to `UI_MESSAGE_MAX_CHARS`
(3900) when `capture_lines` is not supplied. That value is then passed verbatim as
`-S -3900` to `tmux capture-pane`, which interprets it as a **line** count. 3900
lines of scrollback is far more than needed and inflates every capture subprocess
call.

`UI_MESSAGE_MAX_CHARS` is a character budget used for content truncation in UI
adapters, polling output tails, and hook receivers. Conflating it with a line count
is a semantic type error.

### Requirements

- Add `CAPTURE_PANE_LOOKBACK_LINES = 500` to `teleclaude/constants.py`, grouped
  near the existing internal configuration block, with a comment stating it is the
  default tmux scrollback line count for `capture_pane()`.
- Change the fallback in `capture_pane()` to use `CAPTURE_PANE_LOOKBACK_LINES`
  instead of `UI_MESSAGE_MAX_CHARS`. The explicit `capture_lines` argument contract
  is unchanged.
- Do not change any caller that passes explicit `capture_lines` (e.g.
  `command_handlers.py`).
- Do not alter any other usage of `UI_MESSAGE_MAX_CHARS`.

### Verification

- `CAPTURE_PANE_LOOKBACK_LINES = 500` exists in `constants.py` and is imported by
  `tmux_bridge`.
- `capture_pane()` docstring or inline comment identifies the parameter as a line
  count.
- All callers that pass explicit `capture_lines` still work as before.
- Unit test for `capture_pane()` default: assert the command contains `-S -500`
  (not `-S -3900`) when called without `capture_lines`.

---

## R2 — Per-session tmp directory cleanup

### Problem

`tmux_bridge._prepare_session_tmp_dir()` creates `~/.teleclaude/tmp/sessions/{safe_id}/`
per session (used as `TMPDIR` for the session process). `cleanup_session_resources()`
removes the workspace dir but not this tmp dir. Over time, stale tmp directories
accumulate.

Two private helpers exist in `tmux_bridge`: `_get_session_tmp_basedir()` and
`_safe_path_component()`. They are not in `__all__` and cannot be cleanly imported
by `session_cleanup`.

### Requirements

#### 2a — Export helpers from `tmux_bridge`

- Rename `_get_session_tmp_basedir` → `get_session_tmp_basedir` (public).
- Rename `_safe_path_component` → `safe_path_component` (public).
- Add both names to `__all__` in `tmux_bridge.py`.
- Update all internal callers of the private names to use the public names.
- [inferred] The environment variable `TELECLAUDE_SESSION_TMPDIR_BASE` override in
  `get_session_tmp_basedir()` must be preserved as-is.

#### 2b — Tear-down cleanup in `cleanup_session_resources()`

- In `session_cleanup.cleanup_session_resources()`, after the workspace dir removal
  block, add removal of the per-session tmp dir:
  - Compute `safe_id = tmux_bridge.safe_path_component(session_id)`.
  - Compute `tmp_dir = tmux_bridge.get_session_tmp_basedir() / safe_id`.
  - If `tmp_dir` exists, remove it with `shutil.rmtree` wrapped in a try/except
    (best-effort, non-fatal, log a warning on failure).
- The removal must be performed regardless of whether the session had a tmux session
  (headless sessions may also have leftover dirs from prior runs).

#### 2c — Orphan tmp dir sweep in `session_cleanup`

- Add `cleanup_orphan_tmp_dirs() -> int` following the `cleanup_orphan_workspaces()`
  pattern exactly:
  - Check if `get_session_tmp_basedir()` exists; return 0 if not.
  - Get all sessions from DB via `db.get_all_sessions()`.
  - Build `known_safe_ids` by mapping each `session.session_id` through
    `safe_path_component`.
  - Iterate subdirs of the tmp base dir; remove any that are not in `known_safe_ids`.
  - Log and return count.
- Add `cleanup_orphan_tmp_dirs` to the imports in `maintenance_service.py` and call
  it in `periodic_cleanup()` alongside `cleanup_orphan_workspaces()`.

### Verification

- Existing `test_session_cleanup.py` tests still pass.
- New unit test in `test_session_cleanup.py`: mock `get_session_tmp_basedir` and
  `safe_path_component`; assert that `cleanup_session_resources()` attempts to
  remove the computed tmp path.
- New unit test: `cleanup_orphan_tmp_dirs()` removes dirs not in known session set
  and returns correct count.
- `maintenance_service.periodic_cleanup()` calls `cleanup_orphan_tmp_dirs()`.

---

## R3 — Remove per-tick `session_exists()` from output poller

### Problem

`OutputPoller.poll()` calls three subprocess operations each tick:
1. `tmux_bridge.session_exists()` — line 138
2. `tmux_bridge.capture_pane()` — line 199
3. `tmux_bridge.is_pane_dead()` — line 280

All three are async subprocess invocations. `session_exists()` is redundant: an
absent or dead session is observable from the `capture_pane()` return value (empty
string or exception path). `is_pane_dead()` is a secondary liveness check that does
not need to run every tick.

### Requirements

- Remove the per-tick `session_exists_now = await tmux_bridge.session_exists(...)`
  call from the main `while True` loop in `OutputPoller.poll()`.
- Infer session liveness from `capture_pane()` return:
  - If `capture_pane()` returns an empty string and `previous_output` was non-empty,
    treat the session as gone (same exit path as `not session_exists_now` previously).
  - Preserve the watchdog logic (distinguishing expected vs. unexpected exit) by
    checking `session.closed_at` and `lifecycle_status` as before, but triggering on
    the empty-capture signal instead of `session_exists` returning False.
  - [inferred] If `capture_pane()` returns empty on the very first iteration (before
    any output is observed), this is treated as a clean exit with no watchdog alarm,
    consistent with the existing `session_existed_last_poll = True` initialization.
- Move `is_pane_dead()` to a throttled cadence: only call it when
  `poll_iteration % 5 == 0`. Between cadence ticks, skip the `is_pane_dead()` check.
- Remove `session_existed_last_poll` state variable if it is no longer needed after
  the above changes; keep it if still used in the watchdog path.
- Do not change the `ProcessExited` or `OutputChanged` event contracts.
- Do not alter any call outside `OutputPoller.poll()`.

### Verification

- Existing behavioral coverage in `test_output_poller.py` remains green, with test
  updates allowed where prior assertions were coupled to the removed
  `session_exists()` call path.
- New unit test: mock `tmux_bridge.capture_pane` to return empty string after N
  non-empty returns; assert `ProcessExited` is yielded and `session_exists` is never
  called.
- New unit test: mock `tmux_bridge.is_pane_dead` and assert it is called at most
  once every 5 iterations.

---

## R4 — Codex pane snapshot fixture corpus

### Problem

The Codex semantic parser in `polling_coordinator.py` (functions
`_has_live_prompt_marker`, `_extract_prompt_block`, `_find_recent_tool_action`,
`_is_live_agent_marker_line`, `_is_compact_dimmed_agent_boundary_line`) has no
end-to-end fixture coverage. Existing tests construct small, hand-crafted strings
that only hit individual code paths. The subsequent runtime refactor requires a
regression guard that proves semantic parity before and after extraction.

### Requirements

- Create directory `tests/fixtures/codex_pane_snapshots/`.
- Create 8 fixture files, one per semantic state, named `{state}.txt`:

  | Filename              | Semantic state                                            |
  |-----------------------|-----------------------------------------------------------|
  | `startup_prompt.txt`  | Fresh session: Codex prompt marker at bottom, no history  |
  | `typing_partial.txt`  | User is typing: prompt marker present, partial input text |
  | `spinner_active.txt`  | Agent working: live spinner/status line (no prompt)       |
  | `tool_action_read.txt`| Tool in progress: agent marker with "Read" action visible |
  | `tool_done_prompt.txt`| Tool complete, prompt returned: prompt visible in bottom  |
  | `compact_fast_turn.txt`| Fast turn: dimmed agent marker (compact boundary line)   |
  | `stale_scrollback.txt`| Old tool markers in scrollback, live prompt at bottom     |
  | `seeded_prompt.txt`   | Prompt with pre-seeded input text from prior dispatch     |

- Each file must contain **ANSI escape codes** representative of real Codex terminal
  output, not just plain text. Specifically:
  - Prompt marker lines use `CODEX_PROMPT_MARKER` as defined in
    `polling_coordinator.py`, with realistic surrounding text.
  - Compact assistant boundary lines use bullet-glyph markers (e.g. `•`) with the
    ANSI dim signature that `_is_compact_dimmed_agent_boundary_line()` checks for.
  - Live agent marker lines use bullet-glyph markers and status text that
    `_is_live_agent_marker_line()` recognizes.
  - Spinner lines include text like `• working...` or `• Esc to interrupt`.
  - Tool action lines include ANSI bold tokens matching `_ANSI_BOLD_TOKEN_RE`.
- [inferred] Fixtures are representative synthetic content (not from real user
  sessions). They do not need to be byte-for-byte copies of live terminal captures.
- Fixtures are plain UTF-8 text files (`.txt`), not binary.

### Verification

- `tests/fixtures/codex_pane_snapshots/` exists with exactly 8 files.
- Each file is non-empty and contains at least one ANSI escape sequence.
- Fixtures are parseable as UTF-8 strings without error.

---

## R5 — Parser replay tests

### Requirements

- Create `tests/unit/test_codex_replay.py`.
- Load each fixture from `tests/fixtures/codex_pane_snapshots/` (relative to the
  test file's directory or project root, using `Path(__file__).parent`).
- For each fixture, call the relevant pure parser functions from
  `teleclaude.core.polling_coordinator` and assert the expected semantic output.

  | Fixture              | Parser assertions                                                            |
  |----------------------|------------------------------------------------------------------------------|
  | `startup_prompt`     | `_has_live_prompt_marker` → True; `_find_recent_tool_action` → None          |
  | `typing_partial`     | `_has_live_prompt_marker` → True; `_extract_prompt_block` text is non-empty  |
  | `spinner_active`     | `_has_live_prompt_marker` → False; `_is_live_agent_marker_line` on last agent line → True |
  | `tool_action_read`   | `_find_recent_tool_action` → non-None, action word is "Read"; `_has_live_prompt_marker` → False |
  | `tool_done_prompt`   | `_has_live_prompt_marker` → True; `_find_recent_tool_action` may return stale match (OK) |
  | `compact_fast_turn`  | `_is_compact_dimmed_agent_boundary_line` on the boundary line → True         |
  | `stale_scrollback`   | `_has_live_prompt_marker` → True; `_find_recent_tool_action` → None because the visible tool markers are stale |
  | `seeded_prompt`      | `_extract_prompt_block` → returns the seeded text; `_has_live_prompt_marker` → True |

- Tests must pass against the **current** `polling_coordinator.py` code before any
  refactor.
- Tests use the existing pure synchronous parser helpers already exercised by the
  unit test suite; they do not introduce new parser entry points.
- Tests must not import `_maybe_emit_codex_turn_events` or any async stateful
  function — only the pure synchronous parsing helpers.
- Test file follows the project's existing unit test patterns: `pytest` fixtures,
  plain `assert` statements, descriptive test function names.

### Verification

- `tests/unit/test_codex_replay.py` exists.
- `pytest tests/unit/test_codex_replay.py` passes with 8+ test functions (one per
  fixture state at minimum).
- No mocking of tmux or DB required (tests are fully synchronous and pure).
- Tests run in < 1s total and avoid tmux/DB/network I/O beyond local fixture reads.

---

## Constraints

- All changes must pass pre-commit hooks (lint, type-check, existing tests).
- `capture_pane()` public signature is unchanged — `capture_lines` remains an
  optional keyword argument.
- The `UI_MESSAGE_MAX_CHARS` constant must not be removed or renamed; only the
  misuse inside `capture_pane()` is corrected.
- Exported `get_session_tmp_basedir` and `safe_path_component` must preserve the
  exact behavior of their private counterparts.
- Fixture files must not contain real user data or real session content.

## Risks

- **R3 regression risk**: Removing `session_exists()` changes the primary exit
  detection signal. If `capture_pane()` fails silently (returns empty) for a reason
  other than session death, the poller may terminate prematurely. Mitigation: unit
  tests cover the empty-on-death path explicitly; the `is_pane_dead()` fallback at
  every 5th tick provides a secondary check.
- **R4 fixture fidelity**: Synthetic ANSI fixtures may not cover all edge cases that
  real terminal output would expose. This is acceptable — the fixtures act as a
  smoke regression guard, not an exhaustive oracle. Real-capture fixtures are deferred
  to a follow-up.

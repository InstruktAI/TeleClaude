# Input: codex-render-baseline

Split from parent `codex-render-semantic-runtime` — Phase 1 (Immediate Corrections)
and Phase 2 (Replay Corpus and Semantic Baseline).

## What

Deliver the safe, independently shippable baseline fixes and the semantic safety net
that the core runtime refactor depends on.

### Phase 1: Immediate Corrections

1. **Capture budget fix** — Split `UI_MESSAGE_MAX_CHARS` (char budget) from
   `capture-pane` line lookback. Add `CAPTURE_PANE_LOOKBACK_LINES = 500` in
   `constants.py` and use it as the default in `tmux_bridge.capture_pane()`.
   Current regression at `tmux_bridge.py:1031` uses a 3900-char budget as a line
   count for `-S -3900`.

2. **Per-session tmp cleanup** — Extend `cleanup_session_resources()` in
   `session_cleanup.py` to remove `~/.teleclaude/tmp/sessions/{safe_id}`.
   Export `get_session_tmp_basedir` and `safe_path_component` from `tmux_bridge`.
   Add `cleanup_orphan_tmp_dirs()` following the `cleanup_orphan_workspaces()` pattern.

3. **Cheapen the hot loop** — Remove redundant per-tick `session_exists()` call in
   `OutputPoller.poll()`. Infer session liveness from `capture_pane()` return.
   Move `is_pane_dead()` check to a slower cadence (every 5 iterations).

### Phase 2: Replay Corpus

4. **Fixture corpus** — Create `tests/fixtures/codex_pane_snapshots/` with synthetic
   pane captures: startup_prompt, typing_partial, spinner_active, tool_action_read,
   tool_done_prompt, compact_fast_turn, stale_scrollback, seeded_prompt. Each with
   ANSI codes intact.

5. **Parser replay tests** — Write `tests/unit/test_codex_replay.py` that feeds
   fixture snapshots through the Codex semantic parser and asserts expected events.
   These tests become the safety net for the extraction refactor in the next todo.

## Why

These changes deliver immediate value (capture budget fix reduces tmux overhead,
tmp cleanup stops accumulation, hot loop optimization halves per-tick subprocess
count) while establishing the replay corpus that protects semantic parity during
the subsequent code extraction and runtime refactor.

## Success Criteria

- `CAPTURE_PANE_LOOKBACK_LINES` exists and is used as the `capture_pane` default
- Session teardown removes per-session tmp directories
- `session_exists()` no longer runs every poll iteration
- Replay fixture corpus covers all key Codex semantic states
- Replay tests pass against current parser code (pre-refactor baseline)
- All existing tests pass; no behavioral regressions

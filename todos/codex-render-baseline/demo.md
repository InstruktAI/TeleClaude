# Demo: codex-render-baseline

## Validation

```bash
# Verify the lookback constant exists and is used
grep -n "CAPTURE_PANE_LOOKBACK_LINES" teleclaude/constants.py teleclaude/core/tmux_bridge.py
```

```bash
# Verify UI_MESSAGE_MAX_CHARS is no longer misused in tmux_bridge
grep -n "UI_MESSAGE_MAX_CHARS" teleclaude/core/tmux_bridge.py | grep -v "^Binary"
```

```bash
# Verify public helpers are exported from tmux_bridge
python -c "from teleclaude.core.tmux_bridge import get_session_tmp_basedir, safe_path_component; print('OK')"
```

```bash
# Verify cleanup_orphan_tmp_dirs is wired into maintenance
grep -n "cleanup_orphan_tmp_dirs" teleclaude/services/maintenance_service.py
```

```bash
# Verify session_exists is no longer called in the poller hot loop
grep -n "session_exists" teleclaude/core/output_poller.py
```

```bash
# Verify fixture corpus exists with exactly 8 files
ls tests/fixtures/codex_pane_snapshots/ | wc -l
```

```bash
# Run replay tests
pytest tests/unit/test_codex_replay.py -v
```

```bash
# Run the full related unit test suite
pytest tests/unit/test_tmux_bridge.py tests/unit/test_tmux_bridge_tmpdir.py tests/unit/test_session_cleanup.py tests/unit/test_output_poller.py tests/unit/test_codex_replay.py -v
```

## Guided Presentation

**1. Capture budget fix (R1)**

Run the first validation block. You should see `CAPTURE_PANE_LOOKBACK_LINES = 500`
in `constants.py` and the import in `tmux_bridge.py`. The second block should return
no output — confirming `UI_MESSAGE_MAX_CHARS` is no longer misused as a line count.

This means every `capture_pane()` call now fetches at most 500 lines of scrollback
instead of 3900, reducing subprocess data transfer by ~7×.

**2. Tmp dir cleanup (R2)**

Run the third validation block to confirm the public helpers are importable.
Run the fourth block to confirm `cleanup_orphan_tmp_dirs` is called in
`periodic_cleanup`. This means session teardown now removes
`~/.teleclaude/tmp/sessions/{safe_id}/` and the hourly sweep recovers any orphans.

**3. Hot loop optimization (R3)**

Run the fifth validation block. It should return no output — `session_exists` is
not called in the output poller loop. The poller now detects session death from
the `capture_pane()` empty-return signal, halving per-tick subprocess calls.
`is_pane_dead()` now runs at a 1/5 cadence as a secondary check.

**4. Fixture corpus (R4)**

Run the sixth block. Output should be `8`. Each file contains ANSI escape codes
representative of real Codex terminal states.

**5. Parser replay tests (R5)**

Run the seventh block. All 8 tests should pass in < 1s with no tmux/DB mocking.
These tests are the semantic parity guard for the subsequent extraction refactor.

**6. Full suite**

Run the eighth block. All tests should pass with no failures.

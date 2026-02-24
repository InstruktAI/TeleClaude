# Bug:

## Symptom

We dont strip color codes from our output yet:

• Called teleclaude.teleclaude\_\_get_session_data({"computer":"local","session_id":"9ca9e0ce-9464-41c1-a417-bb068e291463","tail_chars":4000})
└ {"status": "success", "session_id": "9ca9e0ce-9464-41c1-a417-bb068e291463", "project_path": "/Users/Morriz/Workspace/InstruktAI/TeleClaude",
"subdir": "trees/textual-footer-migration", "messages":
"2;181;107;145m█\u001b[38;2;182;107;143m█\u001b[38;2;184;106;141m█\u001b[38;2;186;106;139m█\u001b[38;2;187;105;137m
\u001b[38;2;189;105;135m█\u001b[38;2;190;104;133m█\u001b[38;2;192;104;131m█\u001b[38;2;193;103;129m█\u001b[38;2;195;103;127m█\n\u001b[38;2;
71;150;228m░\u001b[38;2;73;149;227m░\u001b[38;2;74;149;227m░\u001b[38;2;76;148;226m \u001b[38;2;77;147;226m \u001b[38;2;79;146;225m
\u001b[38;2;80;146;225m \u001b[38;2;82;145;224m \u001b[38;2;84;144;223m \u001b[38;2;85;144;223m \u001b[38;2;87;143;222m \u0...

This obviously needs to be fixed.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-24

## Investigation

- Read `teleclaude__get_session_data` flow in `teleclaude/mcp/handlers.py` and traced local execution into `teleclaude/core/command_handlers.py:get_session_data`.
- Confirmed the fallback path `_tmux_fallback_payload(...)` is used when transcript files are not yet available.
- Verified `tmux_bridge.capture_pane(...)` captures pane output with `-e`, which includes ANSI escape sequences.
- Found fallback returned `pane_output[-tail:]` directly, with no ANSI sanitization.
- Because truncation happened on raw output, `tail_chars` could start in the middle of an ANSI sequence, producing leaked fragments like `2;181;...m` in the returned `messages`.
- Added and ran a regression unit test that uses ANSI-colored pane output with a small tail window to validate this boundary condition.
- Follow-up build gate report showed `make: *** [test-all] Error 124` despite functional test correctness.
- Traced the failure to a branch-local `tools/test.sh` change that enforced `TEST_TIMEOUT=10` seconds for the entire pytest invocation.
- Re-ran `make test` multiple times; local runs completed around 7-8 seconds, confirming the 10-second cap was too tight and environment-sensitive.

## Root Cause

`get_session_data` tmux fallback returned raw `capture-pane` output without stripping ANSI codes, and it truncated before sanitization. This allowed color codes (and partial escape-sequence fragments when cut mid-sequence) to leak into MCP tool responses.

The remaining build-gate failure was caused by an unrelated branch-local 10-second hard timeout in `tools/test.sh`, which made `make test` flaky under slower scheduler/load conditions and produced intermittent `Error 124`.

## Fix Applied

- Updated `teleclaude/core/command_handlers.py` tmux fallback to:
  - strip ANSI escape codes with `strip_ansi_codes(...)`
  - apply `tail_chars` after sanitization
- Added regression test `test_handle_get_session_data_tmux_fallback_strips_ansi_before_tail` in `tests/unit/test_command_handlers.py` to ensure ANSI is removed and tail slicing no longer leaks partial escape content.
- Re-aligned `tools/test.sh` with main orchestration contract to remove timeout flakiness:
  - default test timeout fallback restored to `20m`
  - xdist worker selection restored to `-n auto`
  - removed branch-only strict 10-second tuning parameters that triggered `Error 124`
- Validation:
  - `make test` passed (`2010 passed, 106 skipped`)
  - `make lint` passed

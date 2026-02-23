# Review Findings: lifecycle-enforcement-gates

## Review Round: 1

## Verdict: APPROVE

## Paradigm-Fit Assessment

- **Data flow**: `run_build_gates()` uses `subprocess.run()` consistent with existing subprocess patterns in the codebase. `format_build_gate_failure()` follows established string formatting patterns (`format_error()`, `format_tool_call()`).
- **Component reuse**: `_find_demo_md()` and `_check_no_demo_marker()` extracted as shared helpers and reused across `validate`, `run`, `create` subcommands. No copy-paste duplication.
- **Pattern consistency**: Function naming (`_demo_validate`, `_demo_run`, etc.) follows existing `_handle_todo_*` conventions. Error handling uses `SystemExit` consistently with the rest of the CLI module. `pre_dispatch` parameter extends `format_tool_call()` cleanly without breaking existing callers.

**Result**: PASS — no paradigm violations found.

## Requirements Trace

| #   | Requirement                   | Implementation                                                                      | Verified |
| --- | ----------------------------- | ----------------------------------------------------------------------------------- | -------- |
| 1   | Demo subcommand refactor      | `_demo_validate`, `_demo_run`, `_demo_create` in `telec.py:1333-1570`               | Yes      |
| 2   | Silent-pass bug fix           | `_demo_run` exits 1 on no blocks (`telec.py:1382-1384, 1394-1396`)                  | Yes      |
| 3   | No-demo escape hatch          | `_check_no_demo_marker` at `telec.py:1282-1294`, used in validate and run           | Yes      |
| 4   | Build gates in next_work      | `run_build_gates()` at `core.py:275-327`, wired at `core.py:2251-2261`              | Yes      |
| 5   | POST_COMPLETION flow change   | `core.py:82-103` — session stays alive until gates pass                             | Yes      |
| 6   | Demo promotion (create)       | `_demo_create` at `telec.py:1468-1511` — copies + minimal snapshot                  | Yes      |
| 7   | snapshot.json reduction       | `_demo_create` generates `{slug, title, version}` only; listing backward-compatible | Yes      |
| 8   | Daemon restart after finalize | `core.py:129` — `make restart` step in POST_COMPLETION[next-finalize]               | Yes      |
| 9   | Lazy state marking            | `mark_phase(build, started)` deferred to `pre_dispatch` at `core.py:2224-2225`      | Yes      |

## Critical

(none)

## Important

(none)

## Suggestions

### S1: Dead code — unreachable return after `_demo_list()`

`telec.py:1549` — `_demo_list()` always raises `SystemExit`, making the `return` statement unreachable. Harmless but inconsistent with other branches in `_handle_todo_demo()` which rely on callees raising SystemExit.

### S2: Timeout message inconsistency

`core.py:322` — Demo validate timeout says `"timed out"` without specifying duration, while test suite timeout at `core.py:301` says `"timed out after 300s"`. For consistency, consider `"timed out after 60s"`.

### S3: `run_build_gates()` exception paths untested

`run_build_gates()` handles `TimeoutExpired` and `OSError` for both gates but is always mocked in `next_work()` tests. Direct unit tests for these exception paths would be valuable for catching message-format regressions, but the function is simple enough that mocking is pragmatic for now.

### S4: Mid-file imports in test_next_machine_hitl.py

`test_next_machine_hitl.py:566-569` — `AsyncMock`, `next_work`, `POST_COMPLETION`, etc. are imported mid-file rather than at the top. Module-level but not at the top of the file. Consistent with the file's existing pattern (env setup before imports at line 9), but worth consolidating for readability.

## Why No Important+ Issues

1. **Paradigm-fit verified**: Checked data flow (subprocess patterns), component reuse (extracted helpers), pattern consistency (naming, error handling, SystemExit usage). No violations found.
2. **Requirements verified**: All 9 in-scope requirements traced to implemented code and corresponding test cases. 15+ test cases cover all specified scenarios from the implementation plan.
3. **Copy-paste duplication checked**: Helper extraction (`_find_demo_md`, `_check_no_demo_marker`) prevents duplication across subcommands. No copy-paste found.
4. **Gate-failure recovery cycle verified**: Traced the full flow: builder done → mark complete → run gates → fail → reset to started → builder fixes → repeat. The `mark_phase(build, complete)` in `format_build_gate_failure()` correctly reflects the builder's claim of completion, which gates then verify. Not a state inconsistency.
5. **Lazy marking deviation documented**: `set_item_phase(IN_PROGRESS)` kept as eager claim (documented in implementation plan). Only `mark_phase(build, started)` deferred to pre_dispatch. The eager claim is safe — next `next_work()` call picks it up regardless.

## Manual Verification Evidence

This delivery modifies internal state machine logic and CLI subcommand routing. All behavior is verified through unit tests (18+ new tests across 4 test files). The demo.md correctly uses `<!-- no-demo: ... -->` marker with detailed justification. Manual CLI verification was not performed as part of this review — the changes are infrastructure that activates during orchestrator-driven workflows, not standalone user-facing features.

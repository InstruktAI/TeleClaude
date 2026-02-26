# Review Findings: integration-safety-gates

## Critical

1. `is_main_ahead()` silently treats git-inspection failures as "safe", which violates the new unknown-state safety gate contract.
   - Location: `teleclaude/core/next_machine/core.py:2052`, `teleclaude/core/next_machine/core.py:2097`
   - Trace with concrete values:
     - `check_finalize_preconditions(cwd="...", slug="x")` gets `dirty_paths=[]`.
     - `is_main_ahead()` hits `GitCommandError` (for example, bad/missing `main` ref in the worktree) and returns `False`.
     - `check_finalize_preconditions()` then returns `None`, so finalize dispatch proceeds instead of returning `ERROR: FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN`.
   - Impact: Under-blocking unsafe finalize attempts when ahead-state cannot actually be determined.
   - Required change: represent ahead-check failures as unknown state (tri-state/exception) and map that to `FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN`.

## Important

1. Finalize preconditions now run before finalize-lock acquisition, which can misclassify lock contention as a dirty-canonical-main failure.
   - Location: `teleclaude/core/next_machine/core.py:2591`, `teleclaude/core/next_machine/core.py:2595`
   - Why this matters:
     - During another session's in-flight finalize, canonical `main` can be transiently dirty between apply sub-steps.
     - A second orchestrator call now evaluates dirty/ahead checks before `acquire_finalize_lock()`, so it may return `FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN` instead of deterministic `FINALIZE_LOCKED`.
   - Impact: Incorrect operator guidance and avoidable over-blocking under concurrent finalize traffic.
   - Required change: acquire/validate finalize lock ownership before applying canonical safety checks for dispatch.

2. New unknown-state gate is not covered by dispatch-path unit tests.
   - Location: `tests/unit/test_next_machine_state_deps.py:743`
   - Evidence:
     - Added tests cover dirty and main-ahead blocked branches plus happy path.
     - No test asserts dispatch behavior when canonical git state is uninspectable (`get_finalize_canonical_dirty_paths -> None` or ahead-check inspection failure).
   - Impact: The documented `FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN` contract can regress without test signal.
   - Required change: add blocked-branch tests for unknown git state in finalize dispatch.

## Suggestions

1. Manual verification evidence is missing for the user-facing `/next-finalize` apply instruction flow.
   - Scope gap: unit tests validate instruction text and dispatch behavior, but no manual/functional evidence in this review that the full operator flow aborts correctly at apply-time re-check boundaries.

## Paradigm-Fit Assessment

- Data flow: The change stays in `next_machine` orchestration flow and does not bypass project data layers.
- Component reuse: New checks reuse existing formatting and git helper patterns (`format_error`, `is_main_ahead`, `_dirty_paths`).
- Pattern consistency: Error-code pattern is consistent, but failure propagation is inconsistent for ahead-state inspection failures (critical finding above).

## Verdict

REQUEST CHANGES

## Fixes Applied

1. Critical: `is_main_ahead()` failure path silently treated as safe.
   - Fix: Changed `is_main_ahead` to tri-state (`bool | None`) and mapped indeterminate ahead-state to `ERROR: FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN` in finalize preconditions.
   - Commit: `270dc858`

2. Important: Finalize preconditions evaluated before finalize lock acquisition.
   - Fix: Reordered finalize dispatch to acquire lock first, then run preconditions, and release lock on precondition failure.
   - Commit: `6150f525`

3. Important: Unknown-state finalize dispatch path lacked unit coverage.
   - Fix: Added dispatch-path tests for unknown canonical git state, indeterminate ahead-state, and lock-first contention short-circuit behavior.
   - Commit: `5d6a32ac`

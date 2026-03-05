# Review Findings: state-machine-gate-sharpening (Round 2)

## Previous Findings Resolution

All 3 Critical and 5 Important findings from round 1 have been properly addressed:

| Issue | Status | Verification |
|-------|--------|-------------|
| C-1: Over-subtraction in merge diff algorithm | Fixed | Replaced with `git log --no-merges --name-only`; regression test added (`test_has_meaningful_diff_file_in_merge_and_real_commit_included`) |
| C-2: `_has_meaningful_diff` called synchronously on event loop | Fixed | Wrapped in `asyncio.to_thread` at core.py:3008 |
| C-3: Demo references wrong test file | Fixed | Now references `test_state_machine_gate_sharpening.py` |
| I-1: No logging on subprocess errors in `_has_meaningful_diff` | Fixed | `logger.warning` with context at core.py:970-973 |
| I-2: Retry path hardcodes config paths | Fixed | Comment at core.py:439-442 explains why paths mirror Makefile |
| I-3: Demo grep produces no output | Fixed | Block uses `grep -B5 "_has_meaningful_diff"` |
| I-4: Missing test for retry TimeoutExpired | Fixed | `test_run_build_gates_retry_timeout_fails_gate` added |
| I-5: Missing artifact verification tests | Fixed | Two tests added for review_round 0 and >0 |

## Critical

None.

## Important

### I-1: Demo narrative describes old algorithm

**File:** `demos/state-machine-gate-sharpening/demo.md:37-39`

The Guided Presentation Step 1 says:

> The function runs `git diff --name-only` between baseline and HEAD, filters out
> `todos/` and `.teleclaude/` paths, excludes merge-introduced files...

The function actually uses `git log --no-merges --name-only --pretty=format:`, not `git diff --name-only`. The C-1 fix in commit `44420b51` replaced the two-pass subtraction algorithm with a single `--no-merges` approach. The narrative was not updated to match. The executable blocks are all correct; only the presenter description is inaccurate.

**Fix:** Update lines 37-39 to describe the actual `git log --no-merges` approach.

## Suggestions

### S-1: Missing structured logging in retry exception handler

**File:** `teleclaude/core/next_machine/core.py:468-473`

The retry error is captured in the output string but no `logger.warning` is emitted. A structured log would make retry failures searchable in log aggregation.

### S-2: Missing structured logging in retry success path

**File:** `teleclaude/core/next_machine/core.py:457-460`

When a retry passes, the event is only captured in the output string. A `logger.info` for flaky test recovery would make flaky test frequency observable via log aggregation without parsing output strings.

### S-3: Strip inconsistency in `_has_meaningful_diff` filter

**File:** `teleclaude/core/next_machine/core.py:966`

`f.strip()` is used as a truthiness guard but `f.startswith(p)` operates on the raw `f`. Harmless in practice since `git log --name-only` never emits leading whitespace on filenames, but `stripped = f.strip()` followed by `stripped.startswith(p)` would be more internally consistent.

## Paradigm-Fit Assessment

1. **Data flow:** All changes follow established patterns — `subprocess.run` for git/make calls, `asyncio.to_thread` for blocking work, `read_phase_state`/`mark_phase` for state transitions. No bypasses.
2. **Component reuse:** `_has_meaningful_diff` and `_count_test_failures` are properly extracted as private helpers following the existing `_get_head_commit` pattern. No copy-paste.
3. **Pattern consistency:** Logging uses the existing `logger` and `_log_next_work_phase` patterns. Error handling follows the established `(subprocess.CalledProcessError, OSError)` convention. Type coercion for YAML state follows the `isinstance` guard pattern used throughout the file.

## Principle Violation Hunt

1. **Fallback & silent degradation:** `_has_meaningful_diff` returns `True` on error (fail-safe: invalidate). `_count_test_failures` returns 0 on no match, causing gate failure (correct direction). No unjustified fallbacks in changed code.
2. **Fail fast:** Boundary validation via `isinstance` guards on YAML state values. Internal code trusts typed function signatures.
3. **DIP:** No adapter imports in core. No transport-specific conditionals.
4. **Coupling:** No deep chains. No god-object dependencies introduced.
5. **SRP:** Each helper has one responsibility. `run_build_gates` is larger with retry but still singular (run build gates).
6. **YAGNI/KISS:** Retry mechanism justified by documented 50% flaky failure rate. No premature abstractions.
7. **Encapsulation:** No direct state mutation. State changes go through `mark_phase`.
8. **Immutability:** `retry_env` creates a new dict. No shared mutable state.

## Requirements Tracing

| Requirement | Implementation | Test |
|---|---|---|
| SC-1: Infra-only diff preserves approval | `_has_meaningful_diff` returns False for todos/ and .teleclaude/ files | `test_next_work_review_approved_infra_only_diff_holds` |
| SC-2: Real diff invalidates approval | `_has_meaningful_diff` returns True for non-infra files | `test_next_work_review_approved_real_diff_invalidates` |
| SC-3: Gate failure with review_round > 0 keeps build=complete | Conditional at core.py:3096 | `test_next_work_gate_failure_review_round_gt_zero_keeps_build_complete` |
| SC-4: Gate failure with review_round == 0 resets build | Conditional at core.py:3096-3100 | `test_next_work_gate_failure_review_round_zero_resets_build` |
| SC-5: Retry on <=2 test failures, passes if retry passes | Retry block at core.py:435-460 | `test_run_build_gates_retry_on_one_failure_passes`, `test_run_build_gates_retry_on_two_failures_passes` |
| SC-6: No retry on >2 failures | Else branch at core.py:474-476 | `test_run_build_gates_no_retry_when_three_failures` |
| SC-7: Combined output on retry failure | Retry failure at core.py:461-467 | `test_run_build_gates_retry_fails_gate_fails_combined_output` |

All seven success criteria have corresponding code paths and test coverage.

## Verdict: APPROVE

0 Critical, 1 Important (demo narrative only — no production code issues), 3 Suggestions. All prior critical and important findings from round 1 have been properly resolved. Production code is correct, well-tested, and follows established patterns. The Important finding is a documentation inaccuracy in a non-executable section of the demo and does not affect code correctness or safety.

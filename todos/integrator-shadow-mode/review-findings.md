# Review Findings: integrator-shadow-mode

## Round 1 (Previous)

All findings addressed. Fixes committed. See commit references below.

### Fixes Applied (Round 1)

- C1: Implementation plan checkboxes marked complete (`a3a70f74`).
- C2: Build Gates checkboxes marked complete (`5838cbc7`).
- C3: Clearance probe excludes integrator owner session; regression coverage added (`438b9ff6`).
- C4: Removed incorrect `pytest.mark.integration` from unit tests (`aa6c332b`).
- I1: `ShadowOutcome.reasons` uses fallback when readiness reasons empty; test added (`85facc42`).
- I2: Constructor validation for `canonical_main_pusher` when `shadow_mode=False`; test added (`d45cbd3c`).
- I3: Lease-loss test added (`bb2988c3`).
- I4: Clearance retry-loop test added (`b2c68d73`).
- I5: Non-shadow-mode canonical push test added (`fac226cc`).
- I6: Queue status transition DAG enforced; invalid-transition tests added (`9627501b`).
- I7: Tests for `readiness is None` and `SUPERSEDED` paths added (`19d0fb31`).

---

## Round 2

### Review Context

- **Review round:** 2
- **Scope:** Full branch diff from `merge-base` to HEAD
- **Verification:** `make lint` passes (pyright 0 errors), `make test` passes (2369 passed, 106 skipped)
- **Round 1 fixes:** All verified in codebase
- **Review lanes:** code (code-reviewer), tests (test-analyzer), error handling (silent-failure-hunter)

### Round 1 Fix Verification

| Finding               | Status | Evidence                                                                                                                             |
| --------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| C3: Self-blocking     | Fixed  | `classify_standalone_sessions` has `exclude_session_id` param (runtime.py:129); called with owner exclusion (runtime.py:110,282,297) |
| C4: Wrong marker      | Fixed  | No `pytestmark` at unit test file top                                                                                                |
| I1: Empty reasons     | Fixed  | Fallback at runtime.py:270; test at unit:234                                                                                         |
| I2: Constructor guard | Fixed  | Validation at runtime.py:199-200; test at unit:216                                                                                   |
| I3: Lease loss test   | Fixed  | `test_shadow_runtime_raises_when_lease_lost_during_drain` at unit:274                                                                |
| I4: Clearance retry   | Fixed  | `test_shadow_runtime_retries_clearance_until_blockers_clear` at unit:334                                                             |
| I5: Non-shadow push   | Fixed  | `test_shadow_runtime_calls_canonical_main_pusher_when_shadow_mode_disabled` at unit:381                                              |
| I6: Transition DAG    | Fixed  | `_ALLOWED_STATUS_TRANSITIONS` at queue.py:16; enforced in `_set_status` at queue.py:196; test at unit:145                            |
| I7: Superseded/None   | Fixed  | Tests at unit:421 and unit:452                                                                                                       |

### Paradigm-Fit Assessment

- **Data flow:** Uses existing `CandidateKey`/`CandidateReadiness` from `readiness_projection`. No data layer bypass.
- **Component reuse:** Composes existing types compositionally. No copy-paste duplication.
- **Pattern consistency:** Follows established integration package conventions — frozen dataclasses, TypedDict payloads, atomic file writes via temp+`os.replace`, custom error classes inheriting `RuntimeError`.

**Result: PASS**

### Requirements Tracing

| Requirement                | Status  | Evidence                                                                                                                                              |
| -------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1: Singleton runtime     | Covered | `lease.py` atomic acquire; concurrency test (unit:22)                                                                                                 |
| FR2: Queue discipline      | Covered | `queue.py` FIFO by `ready_at`; FIFO test (unit:105); transition DAG enforcement (queue.py:16)                                                         |
| FR3: Shadow execution      | Covered | Readiness recheck + `would_integrate`/`would_block`; pusher provided but never called in shadow (unit:161)                                            |
| FR4: Main branch clearance | Covered | Session classification with owner exclusion; tail heuristic; retry loop; housekeeping commit; tests at unit:334,492,517,528                           |
| FR5: Operational safety    | Covered | Lease release in `finally`; queue `_recover_in_progress_items` on init; durable checkpoint; restart test (integration:16); lease-loss test (unit:274) |
| Architecture impact        | Covered | `integration-orchestrator.md` updated with `main_branch_clearance` section and lifecycle step                                                         |

All five verification requirements from `requirements.md` are met.

### Important

#### 1. `git commit` pattern has no main-branch anchor; substring guard amplifies false positives

**File:** `teleclaude/core/integration/runtime.py:43,151`

The `\bgit\s+commit\b` pattern at line 43 matches any `git commit` on any branch — it has no `\bmain\b` anchor, unlike the other five activity patterns. Combined with the substring guard at line 151 (`"main" not in normalized`), this produces concrete false-positive blocking: a session committing to a feature branch whose output contains any word with "main" as substring (e.g., "domain", "maintain") will trigger clearance blocking.

**Impact:** Safe direction — over-blocks, never under-blocks. Acceptable for shadow mode. Must be fixed before cutover.

**Fix:** Either add `\bmain\b` context to the `git commit` pattern (e.g., `r"\bgit\s+commit\b[^\n]*\bmain\b"`), or replace the substring guard with word-boundary matching (`re.search(r"\bmain\b", normalized)`), or both.

#### 2. `finally` block can mask original exception from both `release()` and `_write_checkpoint()`

**File:** `teleclaude/core/integration/runtime.py:244-250`

The `finally` block calls `_lease_store.release()` then `_write_checkpoint()` sequentially. If either raises while an exception from the `try` block is in flight (e.g., `IntegrationRuntimeError` from lease loss), the original exception is replaced. Additionally, if `release()` raises, `_write_checkpoint()` is silently skipped.

**Impact:** Hinders root-cause diagnosis. The lease expires naturally via TTL and the checkpoint is advisory, so no data corruption — but an operator sees a misleading `IntegrationLeaseError` or `OSError` instead of the actual processing failure.

**Fix:** Wrap each `finally` operation in its own `try/except`:

```python
finally:
    try:
        self._lease_store.release(...)
    except Exception:
        pass  # lease will expire via TTL
    try:
        self._write_checkpoint(...)
    except Exception:
        pass  # checkpoint is advisory
```

#### 3. Dirty-tracked-path clearance retry sub-branches untested

**File:** `tests/unit/test_integrator_shadow_mode.py`

`_wait_for_main_clearance` has four paths for dirty tracked paths: (a) committer returns False, (b) no committer provided, (c) post-commit re-check still dirty, (d) committer succeeds. Only (d) is tested via `test_runtime_commits_housekeeping_changes_before_processing`. The three retry sub-paths have no coverage.

#### 4. `lease_acquired=False` runtime path untested

**File:** `tests/unit/test_integrator_shadow_mode.py`

`drain_ready_candidates` returns `RuntimeDrainResult(outcomes=(), lease_acquired=False)` when the lease is busy. No test verifies this path. This is the primary coordination guard — if two integrators race, the loser must return `lease_acquired=False` and refrain from processing.

#### 5. `_break_stale_lock_if_needed` silently swallows broad `OSError`

**File:** `teleclaude/core/integration/lease.py:238-240`

The `except OSError: return` catch handles the intended case (directory not empty), but also silently swallows `PermissionError`, `OSError(EROFS)`, and `OSError(EIO)`. If permissions drift post-deployment, the stale lock can never be broken and every subsequent lock acquisition will timeout with a misleading "timed out waiting for lease mutation lock" error. The actual cause (permission denied) is never surfaced.

**Impact:** Low probability in shadow mode. Should be narrowed before cutover.

**Fix:** Catch only `ENOTEMPTY`/`ENOENT` silently; re-raise other `OSError` subtypes as `IntegrationLeaseError`.

### Suggestions

#### 6. `read()` acquires exclusive mutex unnecessarily

**File:** `teleclaude/core/integration/lease.py:193-197`

Read-only operation holds the file-based directory lock. Since `_persist_leases` uses atomic `os.replace`, reads without locking are safe.

#### 7. TOCTOU in stale-lock breaking

**File:** `teleclaude/core/integration/lease.py:224-240`

Between `stat()` and `rmdir()`, another process can remove the stale lock and acquire a fresh one. The second `rmdir()` could remove the new lock. With default `lock_stale_seconds=30`, practically negligible. Document constraint or consider advisory locks for cutover.

#### 8. `LeaseAcquireResult.holder` ambiguity on self-re-acquire

**File:** `teleclaude/core/integration/lease.py:109-115`

On self-re-acquire, `holder=current` duplicates `lease=current`. No current caller inspects `holder` after success.

#### 9. `enqueue_ready_candidates` public API untested

**File:** `teleclaude/core/integration/runtime.py:204-209`

The READY-candidate filter method has no direct test. Low risk (thin wrapper).

#### 10. Callable type aliases not exported from `__init__.py`

**File:** `teleclaude/core/integration/__init__.py`

The constructor type aliases (`ReadinessLookup`, `SessionsProvider`, `SessionTailProvider`, etc.) are part of the public wiring surface for `IntegratorShadowRuntime` and `MainBranchClearanceProbe` but are absent from `__all__`. Callers must import from the submodule directly.

### Why No Critical Issues (Round 2 Justification)

1. **Paradigm-fit verified:** All new modules follow the existing integration package patterns (file-backed state, atomic writes, frozen dataclasses, TypedDict payloads, Callable dependency injection). No data layer bypass or component duplication found.
2. **Requirements validated:** All FR1-FR5 requirements traced to implementation and test coverage. Verification requirements 1-5 from `requirements.md` each have at least one corresponding test.
3. **Copy-paste duplication checked:** `_resolve_now` and timestamp utilities are duplicated across `lease.py` and `queue.py` as private module helpers with module-specific error types. No behavioral duplication detected in public API.
4. **Round 1 critical fixes all verified:** C3 (self-blocking) confirmed fixed with exclusion parameter; C4 (wrong marker) confirmed removed.
5. **Important findings are safe-direction only:** Finding #1 over-blocks (never under-blocks). Finding #2 is diagnostic quality. Findings #3-4 are secondary test coverage gaps. Finding #5 is a narrow edge case with negligible probability in shadow mode.

---

## Verdict: APPROVE

All round 1 findings addressed. Round 2 Important findings (#1-#5) are either safe-direction heuristic looseness, diagnostic quality improvements, error-handling hardening, or secondary test coverage gaps. None compromise the shadow-mode validation contract. Findings #1, #2, and #5 should be addressed before cutover to non-shadow mode.

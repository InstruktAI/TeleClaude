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
- **Verification:** `make lint` passes (pyright 0 errors), `make test` passes (2333 passed, 106 skipped, 8.53s)
- **Round 1 fixes:** All verified in codebase

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

#### 1. Weak "main" substring guard in clearance heuristic

**File:** `teleclaude/core/integration/runtime.py:151`

The `"main" not in normalized` check is a substring match. Words like "domain", "maintain", "mainline" contain "main" and pass the guard. Combined with the `\bgit\s+commit\b` pattern at line 43 (which has no main-branch context), this can cause false-positive blocking of the clearance loop.

**Impact:** Safe direction — over-blocks, never under-blocks. Acceptable for shadow mode. Should be fixed before cutover.

**Fix:** Replace `if "main" not in normalized:` with `if not re.search(r"\bmain\b", normalized):`.

#### 2. `finally` block can mask original exception

**File:** `teleclaude/core/integration/runtime.py:244-250`

If `_write_checkpoint` raises in the `finally` block while an `IntegrationRuntimeError` is already in flight (e.g., from lease loss), the original exception is replaced. Hinders root-cause diagnosis.

**Fix:** Wrap `_write_checkpoint` in the `finally` with `try/except Exception: pass`.

#### 3. Dirty-tracked-path clearance retry sub-branches untested

**File:** `tests/unit/test_integrator_shadow_mode.py`

`_wait_for_main_clearance` has four paths for dirty tracked paths: (a) committer returns False, (b) no committer provided, (c) post-commit re-check still dirty, (d) committer succeeds. Only (d) is tested via `test_runtime_commits_housekeeping_changes_before_processing`. The three retry sub-paths have no coverage.

#### 4. `lease_acquired=False` runtime path untested

**File:** `tests/unit/test_integrator_shadow_mode.py`

`drain_ready_candidates` returns `RuntimeDrainResult(outcomes=(), lease_acquired=False)` when the lease is busy. No test verifies this path.

### Suggestions

#### 5. `read()` acquires exclusive mutex unnecessarily

**File:** `teleclaude/core/integration/lease.py:193-197`

Read-only operation holds the file-based directory lock. Since `_persist_leases` uses atomic `os.replace`, reads without locking are safe.

#### 6. TOCTOU in stale-lock breaking

**File:** `teleclaude/core/integration/lease.py:224-240`

Between `stat()` and `rmdir()`, another process can remove the stale lock and acquire a fresh one. The second `rmdir()` could remove the new lock. With default `lock_stale_seconds=30`, practically negligible. Document constraint or consider advisory locks for cutover.

#### 7. `LeaseAcquireResult.holder` ambiguity on self-re-acquire

**File:** `teleclaude/core/integration/lease.py:109-115`

On self-re-acquire, `holder=current` duplicates `lease=current`. No current caller inspects `holder` after success.

#### 8. `enqueue_ready_candidates` public API untested

**File:** `teleclaude/core/integration/runtime.py:204-209`

The READY-candidate filter method has no direct test. Low risk (thin wrapper).

### Why No Critical Issues (Round 2 Justification)

1. **Paradigm-fit verified:** All new modules follow the existing integration package patterns (file-backed state, atomic writes, frozen dataclasses, TypedDict payloads, Callable dependency injection). No data layer bypass or component duplication found.
2. **Requirements validated:** All FR1-FR5 requirements traced to implementation and test coverage. Verification requirements 1-5 from `requirements.md` each have at least one corresponding test.
3. **Copy-paste duplication checked:** `_resolve_now` and timestamp utilities are duplicated across `lease.py` and `queue.py` as private module helpers with module-specific error types. No behavioral duplication detected in public API.
4. **Round 1 critical fixes all verified:** C3 (self-blocking) confirmed fixed with exclusion parameter; C4 (wrong marker) confirmed removed.

---

## Verdict: APPROVE

All round 1 findings addressed. Round 2 findings are either safe-direction heuristic looseness (over-blocks, never under-blocks), diagnostic quality improvements, or secondary test coverage gaps. None compromise the shadow-mode validation contract. The Important findings (#1, #2) should be addressed before cutover to non-shadow mode.

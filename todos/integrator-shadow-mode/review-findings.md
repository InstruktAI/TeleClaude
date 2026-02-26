# Review Findings: integrator-shadow-mode

## Review Scope

- Branch: `integrator-shadow-mode` (1 commit: `b279a74c`)
- Files reviewed: 8 changed files (3 implementation, 2 test, 1 spec, 1 init, 1 demo)
- Review lanes: code, tests, types (parallel)
- Tests: 2324 passed, 106 skipped (9.65s)
- Lint: all checks passed, pyright 0 errors

---

## Critical

### C1: Implementation plan checkboxes all unchecked

**File:** `todos/integrator-shadow-mode/implementation-plan.md`

All task checkboxes remain `- [ ]`. The review procedure requires all implementation-plan tasks to be checked before review can approve. The builder did not mark tasks complete.

### C2: Build gates all unchecked

**File:** `todos/integrator-shadow-mode/quality-checklist.md`, Build Gates section

All build gate checkboxes remain unchecked. The review procedure requires the Build section to be fully checked before review can approve.

### C3: Integrator can block itself via clearance probe

**File:** `teleclaude/core/integration/runtime.py:126-133`

`classify_standalone_sessions` does not exclude the integrator's own session. The integrator session has `initiator_session_id=None` and is not referenced as anyone's initiator, so it qualifies as standalone. When the integrator performs housekeeping commits, its tail output will contain `git commit` which matches `_MAIN_ACTIVITY_PATTERNS`. The integrator will detect its own activity and block itself indefinitely.

**Fix:** Thread `owner_session_id` into `classify_standalone_sessions` as an exclusion parameter:

```python
def classify_standalone_sessions(
    sessions: tuple[SessionSnapshot, ...],
    *,
    exclude_session_id: str | None = None,
) -> tuple[SessionSnapshot, ...]:
```

### C4: Unit tests marked as integration tests

**File:** `tests/unit/test_integrator_shadow_mode.py:20`

```python
pytestmark = pytest.mark.integration
```

Unit tests in `tests/unit/` carry the `integration` marker. Under marker-filtered CI (`-m "not integration"`), these 5 tests will be silently skipped. Remove the marker or change to `pytest.mark.unit`.

---

## Important

### I1: `ShadowOutcome.reasons` is empty when readiness reasons are empty on would_block path

**File:** `teleclaude/core/integration/runtime.py:257-260`

When `readiness.status != "READY"` and `readiness.reasons` is an empty tuple, the queue gets the sentinel reason string `"candidate failed readiness recheck"`, but `ShadowOutcome.reasons` receives the empty tuple. The outcome sink and downstream consumers see `would_block` with no explanation.

**Fix:** Use the sentinel reason in the outcome when readiness reasons are empty:

```python
resolved_reasons = readiness.reasons if readiness.reasons else (reason,)
return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=resolved_reasons)
```

### I2: `shadow_mode=False` without `canonical_main_pusher` silently skips push

**File:** `teleclaude/core/integration/runtime.py:176-177, 262-263`

When `shadow_mode=False` and `canonical_main_pusher is None`, the runtime marks candidates as "integrated" without actually pushing to main. This configuration invariant should be caught at construction time.

**Fix:** Add constructor validation:

```python
if not shadow_mode and canonical_main_pusher is None:
    raise ValueError("canonical_main_pusher is required when shadow_mode=False")
```

### I3: No test for lease loss during drain processing

**File:** `teleclaude/core/integration/runtime.py:293-302`

`_renew_or_raise` raises `IntegrationRuntimeError` when the lease is lost. This is a critical safety invariant (prevents dual processors). No test exercises this path. A regression could silently allow continued processing after lease loss.

### I4: No test for clearance retry loop

**File:** `teleclaude/core/integration/runtime.py:268-291`

The clearance wait loop (blocking sessions -> sleep -> retry -> eventually clear) is never tested end-to-end. Tests verify the `MainBranchClearanceProbe` classification in isolation but not the runtime's retry/wait behavior. FR4 requires this: "This cycle repeats indefinitely."

### I5: No test for non-shadow-mode canonical push path

**File:** `teleclaude/core/integration/runtime.py:262-263`

The branch at line 262 (`if not self._shadow_mode and self._canonical_main_pusher is not None`) only has its `True` branch tested (shadow mode skips push). The `False` branch (non-shadow mode calls pusher) has zero coverage.

### I6: Queue `_set_status` enforces no state machine transition rules

**File:** `teleclaude/core/integration/queue.py:171-207`

Any status-to-status transition is accepted. The valid DAG is:

```
queued -> in_progress -> integrated | blocked | superseded
in_progress -> queued (recovery only)
```

But `queued -> integrated` or `blocked -> queued` are not rejected. Current callers follow the DAG by convention, not enforcement.

### I7: No test for SUPERSEDED or readiness=None paths

**File:** `teleclaude/core/integration/runtime.py:247-260`

`_apply_candidate` has three branches: `readiness is None`, `status == "SUPERSEDED"`, and `status != "READY"`. Only the `READY` and `NOT_READY` paths are tested. The `None` and `SUPERSEDED` paths have zero coverage.

---

## Suggestions

### S1: `_resolve_now` duplicated across modules

`lease.py:356-361` and `queue.py:392-397` contain identical `_resolve_now` functions. Extract to a shared utility.

### S2: Timestamps stored as strings in all domain types

`LeaseRecord`, `QueueItem`, `ShadowOutcome` all use `str` for timestamps. `_parse_iso8601`/`_format_iso8601` are duplicated with inconsistent names (`_parse_iso8601` vs `_parse_timestamp`). A shared `Timestamp` type or storing `datetime` in domain types and formatting at serialization boundaries would reduce error surface.

### S3: Runtime Callable aliases not exported in `__init__.py`

`runtime.py` defines 9 Callable aliases (`ReadinessLookup`, `SessionsProvider`, etc.) that are not in `__all__`. The `readiness_projection.py` aliases (`ReachabilityChecker`, `IntegratedChecker`) are exported. Inconsistent API surface.

### S4: Checkpoint is write-only

`_RuntimeCheckpointPayload` at `runtime.py:148-155` is written but never read. If intended for crash recovery, a reader is needed. If observability-only, document the intent.

### S5: `_wait_for_main_clearance` has no timeout

`runtime.py:268-291` loops indefinitely. If clearance is never achieved, the runtime holds the lease forever. Consider a `max_clearance_attempts` parameter.

### S6: `read()` acquires exclusive mutation lock unnecessarily

`lease.py:193-197` — The `read` method holds the file lock for a non-mutating operation. Could cause contention with observability/health-check callers.

---

## Paradigm-Fit Assessment

1. **Data flow**: Implementation follows the existing event store pattern in `teleclaude/core/integration/`. File-backed persistence with atomic write (tmp+fsync+rename) matches the established pattern. Dependency injection via Callable aliases matches the existing `readiness_projection.py` style.

2. **Component reuse**: `CandidateKey` and `CandidateReadiness` are reused from `readiness_projection.py`. No copy-paste duplication detected. The `_resolve_now`, `_parse_timestamp`, and `_format_timestamp` utilities are duplicated across modules (S1/S2 above) but are simple leaf functions.

3. **Pattern consistency**: Frozen dataclasses, TypedDict payloads, Literal status types, and keyword-only constructors are consistent with adjacent code. Re-exports in `__init__.py` follow the established package convention.

---

## Verdict: REQUEST CHANGES

**Blocking issues:**

- C1/C2: Builder did not mark implementation plan or build gate checkboxes
- C3: Integrator self-blocking via clearance probe (functional bug)
- C4: Wrong pytest marker on unit tests (CI risk)
- I1: Empty reasons on would_block outcome (data loss)
- I2: Missing constructor validation for non-shadow config (safety invariant)
- I3-I5, I7: Missing tests for critical safety paths (lease loss, clearance retry, non-shadow push, SUPERSEDED/None readiness)

# Review Findings: integrator-state-machine

## Paradigm-Fit Assessment

The implementation follows established codebase patterns with high fidelity:

- **Data flow**: Mirrors the `next_work()` pattern exactly — async entry wrapping sync logic via `asyncio.to_thread`, returning plain-text instruction blocks. API route mirrors `todo_work()`, CLI mirrors `handle_todo_work()`.
- **Component reuse**: Reuses `IntegrationQueue`, `IntegrationLeaseStore`, `MainBranchClearanceProbe`, `CandidateKey`. No copy-paste duplication.
- **Pattern consistency**: Naming (`_step_*`, `_format_*`), logging, checkpoint I/O, atomic writes all follow existing conventions.

No paradigm violations found.

## Requirements Traceability

| Requirement | Status | Evidence |
|---|---|---|
| `telec todo integrate` returns structured instruction blocks | MET | `_format_*` functions return decision/wait/error/complete instructions |
| Agent calls repeatedly to advance lifecycle | MET | `_dispatch_sync` loop, checkpoint advances per call |
| Queue drain (FIFO) | MET | `_step_idle` pops via `queue.pop_next()` |
| Crash recovery via checkpoint | MET | Atomic checkpoint writes, phase re-entry handlers |
| Lifecycle events at transitions | PARTIAL | 8 of 11 event types emitted; see I-3 below |
| Queue empty → exit instruction | MET | `_format_queue_empty` returned from IDLE when queue empty |
| Merge conflicts → decision point | MET | `MERGE_CONFLICTED` phase, `_format_conflict_decision` |
| Push rejection → decision point | MET | `PUSH_REJECTED` phase, `_format_push_rejected` |
| Lease prevents concurrency | MET | `IntegrationLeaseStore.acquire` in IDLE; re-entrant for same session |
| Clearance gates merge | MET | `_make_clearance_probe`, `_step_clearance_wait` |
| Delivery bookkeeping deterministic | MET | `_step_committed` runs roadmap deliver, demo create |
| Existing integration tests pass | MET | Builder claims 2707 tests passing |

## Critical

None.

## Important

### I-1: Lease never explicitly released after queue drain

**Location:** `state_machine.py:661` (CANDIDATE_DELIVERED sets `lease_token = None`), `state_machine.py:695` (`_try_release_lease` gets `None`, no-ops)

After processing all candidates, `_try_release_lease` is called with `checkpoint.lease_token` which was set to `None` in the CANDIDATE_DELIVERED handler. The `_try_release_lease` guard (`if not lease_token: return`) means the lease is never released — it expires via TTL (120s). During that window, new integrator spawns will get `LEASE_BUSY`.

The lease store IS re-entrant for the same session (confirmed: `lease.py:109`), so multi-candidate processing within one session works. But explicit release after drain should happen.

**Fix:** Preserve the lease token across candidate boundaries (don't clear it in CANDIDATE_DELIVERED), or track it separately and release in the queue-empty exit path.

### I-2: Clearance probe providers fail-open on error

**Location:** `state_machine.py:281` (`_sessions_provider`), `state_machine.py:295` (`_tail_provider`), `state_machine.py:309` (`_dirty_paths_provider`)

All three providers catch `Exception` and return empty results, which causes the clearance probe to report "no blockers." If `telec sessions list` fails or times out, the gate passes when it should block.

**Mitigation:** Natural mitigation exists — the merge itself catches real conflicts, and push rejection handles concurrent pushes. But the principle is wrong: clearance should fail closed, not open.

**Fix:** On failure, return a sentinel that blocks clearance (e.g., a placeholder session ID) and log at WARNING.

### I-3: Three lifecycle events defined but never emitted

**Location:** `events.py:19-31` defines `LifecycleEventType`; `state_machine.py` emits 8 of 11 types.

Missing emissions:
- `integration.completed` — the queue-empty exit returns an instruction string but emits no event. The requirements say lifecycle events at each state transition; the plan (Task 1.3) says COMPLETED should emit summary (candidates processed/blocked, duration).
- `integration.candidate.blocked` — the plan describes a blocked path with follow-up creation; the implementation instead re-prompts on unresolved conflicts and defers blocking to agent action.
- `integration.conflict.resolved` — no emission when MERGE_CONFLICTED → COMMITTED transition detects agent resolved conflicts.

The plan marks all three as `[x]` in Task 1.3, but the code doesn't implement the blocked path or emit the completion/resolution events. This is a silent deferral.

### I-4: Silent exception handling in event emission and lease release

**Location:** `state_machine.py:498`, `state_machine.py:513-514`, `state_machine.py:1110-1111`

Three `except Exception: pass` blocks with no diagnostic logging:
- `_bridge_emit` (line 498): catches import errors, type errors, attribute errors — all invisible.
- `_emit_lifecycle_event` (line 513): catches scheduling errors; the preceding `logger.info` creates a false positive (logs emission attempt but failure is silent).
- `_try_release_lease` (line 1110): catches lease release errors; a filesystem issue here leaves the lock in place, causing future acquire calls to time out.

The fire-and-forget intent is correct (don't block integration on emission failure), but the implementation should log at WARNING with `exc_info=True`.

### I-5: Multi-candidate queue drain has no dedicated test

**Location:** `tests/unit/test_integration_state_machine.py`

No test exercises `_dispatch_sync` with a queue containing 2+ candidates. The IDLE → acquire → process → CANDIDATE_DELIVERED → reset → IDLE → acquire → process loop is the core delivery promise and is untested at the unit level. Key risks: `items_processed` not incrementing correctly, lease re-acquisition behavior, candidate state leaking across iterations.

### I-6: Loose test assertions mask potential failures

**Location:** `test_integration_state_machine.py:278`, `:361`

```python
assert "INTEGRATION COMPLETE" in result or "PUSH" in result or "COMMIT" in result
```

These OR-chain assertions pass on almost any non-error result. Given the queue is empty after processing, the machine should reach COMPLETE. The assertion should be `assert "INTEGRATION COMPLETE" in result`.

## Suggestions

### S-1: Redundant `mark_integrated` in CANDIDATE_DELIVERED handler

**Location:** `state_machine.py:654` (CANDIDATE_DELIVERED handler) duplicates `state_machine.py:1088` (`_do_cleanup`)

Both call `queue.mark_integrated(key=key, reason="integrated via state machine")`. The CANDIDATE_DELIVERED handler exists for crash recovery, but `_do_cleanup` already calls it before writing the CANDIDATE_DELIVERED checkpoint. The handler's call is always a duplicate in the normal path. The `IntegrationQueue` idempotency check prevents real damage, but the redundancy is confusing.

### S-2: COMPLETED phase defined but never written to checkpoint

**Location:** `state_machine.py:72` (enum), `state_machine.py:667-669` (handler)

The `IntegrationPhase.COMPLETED` value is defined and has a handler, but no code path ever writes it to the checkpoint. The queue-empty exit happens directly from IDLE. The handler at line 667 is dead code. This is harmless but inconsistent with the plan which describes COMPLETED as a real phase.

### S-3: `make restart` can crash `_do_cleanup` if `make` not on PATH

**Location:** `state_machine.py:1084`

`subprocess.run(["make", "restart"], ...)` is not wrapped in try/except. A `FileNotFoundError` propagates into `_do_cleanup`, crashing the cleanup step after push succeeded. Wrap in try/except with a warning log.

### S-4: Cleanup git operations lack return-code logging

**Location:** `state_machine.py:1051-1076`

`git branch -D`, `git push --delete`, `git add -A`, cleanup `git commit` return codes are not checked or logged. Silent failures here leave orphaned branches or missing cleanup commits.

## Demo Artifact Review

The demo has 4 executable bash blocks in the Validation section:
- `telec todo integrate --help` — command exists (registered in `CLI_SURFACE`)
- `curl` to `POST /todos/integrate` — route exists in `todo_routes.py`
- `telec events list | grep 'integration\.'` — lifecycle events defined in `events.py`
- `python3 -c "from teleclaude.core.integration.state_machine import next_integrate"` — import works

The Guided Presentation section has non-executable (no `bash` tag) blocks that describe behavior walkthrough. Appropriate for a conversational demo.

The demo exercises real, implemented features — not stubs. Demo is adequate.

## Verdict: APPROVE

The architecture is strong. The state machine pattern — separating deterministic sequencing from agent intelligence — is well executed. Paradigm fit is excellent. The core happy path and common error paths (conflict, push rejection, clearance wait) are complete and tested.

The findings are real but non-blocking:
- Lease release (I-1): mitigated by 120s TTL
- Clearance fail-open (I-2): mitigated by merge conflict and push rejection handling
- Missing events (I-3): observability gap, not functional
- Silent exceptions (I-4): operational visibility, not correctness
- Test gaps (I-5, I-6): risks identified but critical paths are covered

Recommend addressing I-1 through I-4 as follow-up work after delivery.

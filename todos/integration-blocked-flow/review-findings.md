# Review Findings: integration-blocked-flow

## Requirements Traceability

| Requirement                        | Implemented | Tested | Evidence                                                                                                                         |
| ---------------------------------- | ----------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| FR1: Evidence-Rich Blocked Outcome | Yes         | Yes    | `IntegrationBlockedPayload` in `events.py:46-56`, `_emit_blocked_outcome` in `runtime.py:440-478`                                |
| FR2: Resumable Follow-Up Workflow  | Yes         | Yes    | `BlockedFollowUpStore.ensure_follow_up` in `blocked_followup.py:67-117`, idempotency verified in test 2                          |
| FR3: Safe Resume                   | Yes         | Yes    | `resume_from_follow_up` / `resume_blocked_candidate` in `runtime.py:264-344`, readiness recheck + lease guard verified in test 3 |

All three verification requirements are covered by integration tests. All implementation-plan tasks are checked.

## Paradigm-Fit Assessment

1. **Data flow**: Implementation uses the established event system (`build_integration_event`), queue (`IntegrationQueue`), lease (`IntegrationLeaseStore`), and readiness projection. No bypass of existing data layers.
2. **Component reuse**: Good. Reuses `CandidateKey`, `CandidateReadiness`, `MainBranchClearanceProbe`, and existing Literal/TypedDict/dataclass patterns. New `BlockedFollowUpStore` mirrors `IntegrationQueue` and `IntegrationLeaseStore` structure exactly.
3. **Pattern consistency**: Excellent. Frozen dataclasses for domain objects, TypedDicts for serialization, Literal for status types, atomic file persistence via temp+replace, module-private helpers with `_` prefix.

No paradigm violations found.

## Critical

None.

## Important

### 1. `build_integration_event` return value discarded in `_emit_blocked_outcome`

**File:** `teleclaude/core/integration/runtime.py:474`

```python
build_integration_event("integration_blocked", event_payload)
```

The call validates the payload (correct) but discards the canonical `IntegrationEvent` (event_id, idempotency_key, received_at). Persistence is entirely the caller's responsibility via `_blocked_outcome_sink`, which receives the raw `IntegrationBlockedOutcome` dataclass. The test works around this by re-building the event inside the sink callback (test lines 48-63), duplicating construction logic.

This creates a fragile contract: the runtime validates the event but does not persist it. Two independent `build_integration_event` calls (one in runtime, one in the sink) produce different event_ids and idempotency_keys for the same logical event.

**Recommendation:** Either return the built event and pass it to the sink, or have the sink typed to accept `IntegrationEvent` directly.

### 2. `ensure_follow_up` does not refresh todo files on repeat calls

**File:** `teleclaude/core/integration/blocked_followup.py:179-199`

When `ensure_follow_up` is called a second time for the same candidate (update path, lines 75-92), `_ensure_follow_up_todo` runs but the `if not requirements_path.exists()` guard (line 184) skips regeneration. The in-memory state and persisted JSON correctly reflect updated `conflict_evidence` and `diagnostics`, but the todo's `requirements.md` on disk remains stale from the first call.

If the intent is write-once (documents are human-edited after scaffolding), this is acceptable but should be documented. If the intent is that `requirements.md` reflects the latest evidence, this is a gap.

### 3. No integration test for `blocked_follow_up_linker` round-trip

Test 1 does not provide a `blocked_follow_up_linker`, so `follow_up_slug` is always empty. No test exercises the full path where:

1. A `blocked_follow_up_linker` returns a slug
2. That slug appears in the persisted event payload
3. The checkpoint's `last_follow_up_slug` is populated

This is the core linkage path between blocked outcomes and follow-up todos via the runtime.

## Suggestions

### 4. `IntegrationBlockedOutcome.follow_up_slug` uses empty-string sentinel

**File:** `teleclaude/core/integration/runtime.py:111`

The field is `str` initialized with `""` rather than `str | None` with `None`. Consumers must use `if blocked.follow_up_slug:` instead of `if blocked.follow_up_slug is not None:`. Using `str | None` would make the "not yet linked" state explicit in the type system.

### 5. `ResumeBlockedResult` allows invalid state combinations

**File:** `teleclaude/core/integration/runtime.py:114-120`

Five of eight possible field combinations (`resumed` x `key` x `reason`) are semantically invalid but constructable. A `__post_init__` could enforce the invariants cheaply.

### 6. Resume checkpoint writes `outcome=None` — history invisible

**File:** `teleclaude/core/integration/runtime.py:297,337`

Both the lease-contention path and the successful-resume path write `_write_checkpoint(outcome=None)`. The checkpoint's `last_*` fields are only populated by `drain_ready_candidates`, making resume operations invisible to checkpoint readers.

### 7. Additional test coverage opportunities

- Empty/whitespace `follow_up_slug` in `resume_from_follow_up` (validation branch at line 269-271)
- Lease contention during `resume_blocked_candidate` (line 296-300)
- `mark_resolved` on an unknown follow-up slug (error path at line 123-124)
- `_derive_conflict_evidence` / `_derive_next_action` heuristic branches for superseded, missing, and fallback cases
- `BlockedFollowUpStore` persistence round-trip (reload from disk after persist)

### 8. Runtime constructor parameter growth

`IntegratorShadowRuntime.__init__` now has 17 parameters. Consider grouping the four blocked-flow callbacks into a strategy/configuration dataclass to reduce signature complexity.

## Verdict: APPROVE

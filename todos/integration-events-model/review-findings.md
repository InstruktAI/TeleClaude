# Review Findings: integration-events-model

**Review round:** 2
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 14 changed files, 1593 insertions

## Round 1 Fix Verification

All 9 Important findings from round 1 have been verified as correctly resolved:

| #   | Finding                        | Fix commit | Verified                                                                                                                                                         |
| --- | ------------------------------ | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Supersession tie-break         | `cd0a19c6` | `supersession_rank()` returns `(ready_at, branch, sha)` with deterministic ordering. Test `test_service_breaks_equal_ready_at_ties_deterministically` validates. |
| 2   | Auto-replay on init            | `f4dd8a8b` | `__init__` calls `self.replay()` at service.py:47. Test `test_service_replays_history_on_init` validates.                                                        |
| 3   | \_normalize_iso8601 event_type | `ab5697db` | Accepts `event_type: IntegrationEventType` at events.py:306. Test `test_build_event_reports_correct_event_type_for_received_at_validation` validates.            |
| 4   | Reuse compute_idempotency_key  | `7e95d517` | event_store.py imports and calls `compute_idempotency_key` at lines 55, 108. No duplicate.                                                                       |
| 5   | cast in from_record            | `efa9cd04` | events.py:200-202 uses `cast(str, ...)` after diagnostic guard.                                                                                                  |
| 6   | Replay durability test         | `b713bfdd` | Unit `test_service_replays_history_on_init` + integration `test_replay_restores_readiness_after_restart`.                                                        |
| 7   | Contract tests                 | `76261828` | `test_required_fields_contract_matches_integration_spec` asserts `_REQUIRED_FIELDS` == spec YAML.                                                                |
| 8   | ingest_raw tests               | `02dfcbe6` | `test_service_ingest_raw_accepts_valid_event_type` + `test_service_ingest_raw_rejects_unknown_event_type`.                                                       |
| 9   | Checker exports                | `2bc35e06` | `ReachabilityChecker` and `IntegratedChecker` in `__init__.py` `__all__`. Test `test_public_api_exports_checker_type_aliases` validates.                         |

## Paradigm-Fit Assessment

1. **Data flow:** Domain-core pattern maintained. All types express domain meaning (`IntegrationEvent`, `CandidateReadiness`, `ReadinessStatus`). File-backed persistence behind `IntegrationEventStore` abstraction. No transport or UI coupling. Boundary purity preserved.
2. **Component reuse:** Round 1's `_event_digest` duplication (Important #4) resolved. No copy-paste of existing codebase components detected.
3. **Pattern consistency:** Frozen dataclasses for immutable domain objects, TypedDict for serialization contracts, Literal for closed sets, explicit validation at boundaries. Naming is domain-semantic throughout.

## Contract Fidelity (FR1)

Verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly (slug, approved_at, review_round, reviewer_session_id)
- `finalize_ready` fields: match exactly (slug, branch, sha, worker_session_id, orchestrator_session_id, ready_at)
- `branch_pushed` fields: match exactly (branch, sha, remote, pushed_at, pusher)
- Readiness predicate: all conditions implemented in `_recompute()` including reachability and already-integrated checks
- `worktree dirty -> clean` correctly excluded (no reference in projection logic)
- Contract regression test (`test_required_fields_contract_matches_integration_spec`) guards spec-code parity

## Requirements Traceability

| Requirement                       | Implementation                                                 | Test coverage                                                                                                                                      |
| --------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1: Event fidelity               | events.py `_REQUIRED_FIELDS`, `validate_event_payload`         | `test_validate_event_payload_rejects_missing_and_unexpected_fields`, `test_required_fields_contract_matches_integration_spec`                      |
| FR2: Durable idempotent ingestion | event_store.py `append()` with fsync + idempotency key         | `test_event_store_append_is_idempotent_and_collision_safe`, `test_service_replays_history_on_init`, `test_replay_restores_readiness_after_restart` |
| FR3: Readiness projection         | readiness_projection.py `_recompute()`                         | `test_candidate_transitions_from_not_ready_to_ready`                                                                                               |
| FR4: Supersession                 | readiness_projection.py `supersession_rank()` + `_recompute()` | `test_service_marks_older_finalize_candidate_as_superseded`, `test_service_breaks_equal_ready_at_ties_deterministically`                           |

## Important

### 1. FR3.2 reachability/already-integrated failure paths untested

**File:** `readiness_projection.py:195-199`, all test files

The projection correctly implements FR3.2's reachability and not-already-integrated checks:

```python
if branch_pushed and not self._reachability_checker(key.branch, key.sha, self._remote):
    reasons.append(f"sha {key.sha} is not reachable from {self._remote}/{key.branch}")

if self._integrated_checker(key.sha, f"{self._remote}/main"):
    reasons.append(f"sha {key.sha} already reachable from {self._remote}/main")
```

However, no test exercises either negative path. All tests use `_always_reachable` and `_never_integrated` stubs. A regression in these branches would go undetected.

Missing test cases:

- Candidate where `reachability_checker` returns `False` after `branch_pushed` exists -> status `NOT_READY` with reachability reason.
- Candidate where `integrated_checker` returns `True` -> status `NOT_READY` with already-integrated reason.

**Impact:** The code is correct and the logic is straightforward (two if-conditions appending reasons). The explicit Verification Requirements (VR1-VR3) are all met. This gap affects secondary coverage for injected checker callbacks, not a contract violation.

## Suggestions

### S1. Redundant `replay()` in integration test

**File:** `tests/integration/test_integration_readiness_projection.py:137`

`test_replay_restores_readiness_after_restart` calls `restarted.replay()` explicitly, but `__init__` now auto-replays (Fix #2). The explicit call makes the test pass even if constructor-replay regresses. The unit test `test_service_replays_history_on_init` correctly relies on constructor-only replay, so the path IS covered — this is a test hygiene issue, not a coverage gap. Either remove the call or add a comment explaining intentional double-replay idempotency testing.

### S2. `event_id` whitespace inconsistency (carried from round 1 S1)

`build_integration_event` (events.py:130) doesn't strip `event_id` before the empty check, but `integration_event_from_record` (events.py:189) does. An `event_id=" "` would pass the build path but fail round-trip through persistence.

### S3. Redundant diagnostics for missing fields (carried from round 1 S2)

When a field is missing, both `_validate_field_set` and `_as_non_empty_str` report the same root cause, producing duplicate diagnostic messages.

### S4. No diagnostic for mismatched-remote `branch_pushed` (carried from round 1 S3)

A push with `remote="upstream"` is silently ignored when the projection expects `remote="origin"`. An explicit diagnostic would aid operator debugging.

## Why No Critical or Blocking Issues

1. **Paradigm-fit verified:** Domain-core pattern, no transport coupling, clean store abstraction. No copy-paste duplication.
2. **All FR1-FR4 requirements implemented correctly:** Traced through code with concrete values. Supersession tie-breaking, auto-replay, ISO8601 validation, idempotency, and contract fidelity all verified.
3. **All 9 round 1 Important fixes verified:** Each fix traced to its commit, code change, and test evidence.
4. **All explicit Verification Requirements met:** VR1 (unit tests for validation/idempotency/supersession), VR2 (integration test for NOT_READY -> READY), VR3 (contract tests matching spec YAML).
5. **Important #1 above is a test coverage gap for injected checker callbacks, not a logic defect.** The code is correct, the branches are simple, and the risk is low. The explicit VR list is satisfied.

## Verdict: APPROVE

**Rationale:**

- All 9 Important findings from round 1 are verified as correctly resolved with corresponding commits and test evidence.
- FR1-FR4 are fully implemented and traceable to tests.
- All three explicit Verification Requirements (VR1-VR3) are met.
- Contract fidelity confirmed against `docs/project/spec/integration-orchestrator.md`.
- Paradigm-fit assessment shows clean domain-core patterns with no transport coupling.
- One Important finding (FR3.2 checker failure paths untested) is recorded for follow-up but is not blocking: the code is correct, the logic is straightforward, and the explicit VR list is satisfied.
- Carried suggestions (S2-S4) from round 1 remain non-blocking.

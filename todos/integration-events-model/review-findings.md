# Review Findings: integration-events-model

**Review round:** 2
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 12 changed files, ~1505 insertions
**Reviewer:** Claude (manual code review)

## Round 1 Fix Verification

All 9 Important findings from round 1 are verified as correctly resolved:

| #   | Finding                         | Fix commit | Verified                                                                                                                                                                                               |
| --- | ------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Supersession tie-break          | `cd0a19c6` | `supersession_rank()` returns `(ready_at, branch, sha)` for deterministic ordering. `>=` in supersession check (line 173). Test `test_service_breaks_equal_ready_at_ties_deterministically` validates. |
| 2   | Auto-replay on init             | `f4dd8a8b` | `__init__` calls `self.replay()` at service.py:47. Test `test_service_replays_history_on_init` validates.                                                                                              |
| 3   | `_normalize_iso8601` event_type | `ab5697db` | Accepts `event_type: IntegrationEventType` at events.py:306. Test `test_build_event_reports_correct_event_type_for_received_at_validation` validates.                                                  |
| 4   | Reuse `compute_idempotency_key` | `7e95d517` | event_store.py imports and calls `compute_idempotency_key` at lines 55, 108. No duplicate implementation.                                                                                              |
| 5   | `cast` in `from_record`         | `efa9cd04` | events.py:200-202 uses `cast(str, ...)` after diagnostic guard.                                                                                                                                        |
| 6   | Replay durability test          | `b713bfdd` | Unit `test_service_replays_history_on_init` + integration `test_replay_restores_readiness_after_restart`.                                                                                              |
| 7   | Contract tests                  | `76261828` | `test_required_fields_contract_matches_integration_spec` asserts `_REQUIRED_FIELDS` == spec YAML.                                                                                                      |
| 8   | `ingest_raw` tests              | `02dfcbe6` | `test_service_ingest_raw_accepts_valid_event_type` + `test_service_ingest_raw_rejects_unknown_event_type`.                                                                                             |
| 9   | Checker exports                 | `2bc35e06` | `ReachabilityChecker` and `IntegratedChecker` in `__init__.py` `__all__`. Test `test_public_api_exports_checker_type_aliases` validates.                                                               |

## Paradigm-Fit Assessment

1. **Data flow:** Domain-core pattern maintained. All types express domain meaning (`IntegrationEvent`, `CandidateReadiness`, `ReadinessStatus`). File-backed persistence behind `IntegrationEventStore` abstraction. No transport or UI coupling. Boundary purity preserved.
2. **Component reuse:** No copy-paste of existing codebase components. Round 1's `_event_digest` duplication resolved.
3. **Pattern consistency:** Frozen dataclasses for immutable domain objects, TypedDict for serialization, Literal for closed sets, explicit validation at boundaries. Naming is domain-semantic.

## Contract Fidelity (FR1)

Verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly (slug, approved_at, review_round, reviewer_session_id)
- `finalize_ready` fields: match exactly (slug, branch, sha, worker_session_id, orchestrator_session_id, ready_at)
- `branch_pushed` fields: match exactly (branch, sha, remote, pushed_at, pusher)
- Readiness predicate conditions 1-6: all implemented in `_recompute()`
- `worktree dirty -> clean` correctly excluded
- Contract regression test guards spec-code parity

## Requirements Traceability

| Requirement                       | Implementation                                                 | Test coverage                                                                                                                                      |
| --------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1: Event fidelity               | events.py `_REQUIRED_FIELDS`, `validate_event_payload`         | `test_validate_event_payload_rejects_missing_and_unexpected_fields`, `test_required_fields_contract_matches_integration_spec`                      |
| FR2: Durable idempotent ingestion | event_store.py `append()` with fsync + idempotency key         | `test_event_store_append_is_idempotent_and_collision_safe`, `test_service_replays_history_on_init`, `test_replay_restores_readiness_after_restart` |
| FR3: Readiness projection         | readiness_projection.py `_recompute()`                         | `test_candidate_transitions_from_not_ready_to_ready`                                                                                               |
| FR4: Supersession                 | readiness_projection.py `supersession_rank()` + `_recompute()` | `test_service_marks_older_finalize_candidate_as_superseded`, `test_service_breaks_equal_ready_at_ties_deterministically`                           |

## Important

### 1. FR3.2 reachability/already-integrated checker failure paths untested

**File:** `readiness_projection.py:195-199`, all test files

The projection correctly implements FR3.2's reachability and not-already-integrated checks. However, no test exercises either negative path. All tests use `_always_reachable` and `_never_integrated` stubs.

Missing test cases:

- Candidate where `reachability_checker` returns `False` after `branch_pushed` exists -> `NOT_READY` with reachability reason.
- Candidate where `integrated_checker` returns `True` -> `NOT_READY` with already-integrated reason.

**Impact:** Non-blocking. The code is correct (two straightforward if-conditions), the explicit Verification Requirements (VR1-VR3) are all satisfied, and the risk is low. Recorded for follow-up.

## Suggestions

### S1. `event_id` whitespace inconsistency

`build_integration_event` (events.py:130) doesn't strip `event_id`, but `integration_event_from_record` (events.py:189) does. An `event_id=" "` passes the build path but fails round-trip persistence.

### S2. Redundant diagnostics for missing fields

When a field is missing, both `_validate_field_set` and `_as_non_empty_str` report the same root cause, producing duplicate messages.

### S3. No diagnostic for mismatched-remote `branch_pushed`

A push with `remote="upstream"` is silently ignored when the projection expects `remote="origin"`. An explicit diagnostic would aid operator debugging.

### S4. Unrelated `test_discord_adapter.py` change

The mock addition (lines 807-808) is orthogonal to this feature. Would be cleaner in a separate commit.

### S5. Build gates and implementation plan unchecked in HEAD

The merge-with-main at `4ce6a475` reverted the checked boxes from `fdbd62e3`. The substantive evidence exists — all code is complete, tests pass, lint passes. Clerical artifact only.

## Quality Evidence

- **Tests:** 2305 passed, 106 skipped (9.79s)
- **Lint:** ruff format clean, ruff check clean, pyright 0 errors
- **Contract:** `_REQUIRED_FIELDS` matches `required_event_fields` in spec YAML (guarded by test)

## Verdict: APPROVE

**Rationale:**

- All 9 Important findings from round 1 verified as correctly resolved with commits and test evidence.
- FR1-FR4 fully implemented and traceable to tests.
- All three Verification Requirements (VR1-VR3) met.
- Contract fidelity confirmed against `docs/project/spec/integration-orchestrator.md`.
- Paradigm-fit: clean domain-core patterns, no transport coupling, no duplication.
- One Important finding (FR3.2 checker paths untested) recorded for follow-up but non-blocking.

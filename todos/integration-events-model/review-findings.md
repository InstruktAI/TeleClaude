# Review Findings: integration-events-model

**Review round:** 2
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 9 changed files, 1143 insertions

## Round 1 Fix Verification

All 9 Important findings from round 1 have been verified as resolved:

| #   | Finding                         | Verification                                                                                                                                                                                              |
| --- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Supersession tie-break          | `supersession_rank()` returns `(ready_at, branch, sha)` for deterministic ordering; `>=` in supersession check. Test `test_service_breaks_equal_ready_at_ties_deterministically` covers equal timestamps. |
| 2   | No auto-replay on init          | `IntegrationEventService.__init__` calls `self.replay()` at line 47. Test `test_service_replays_history_on_init` verifies.                                                                                |
| 3   | `_normalize_iso8601` event type | Now accepts `event_type: IntegrationEventType` as first parameter. Test `test_build_event_reports_correct_event_type_for_received_at_validation` confirms correct attribution.                            |
| 4   | Duplicate digest function       | `event_store.py` imports and uses `compute_idempotency_key` from `events.py` — no duplication.                                                                                                            |
| 5   | Type narrowing gap              | `integration_event_from_record` uses `cast(str, ...)` for narrowed variables at lines 200-202. Test `test_integration_event_from_record_accepts_valid_string_fields` exercises this path.                 |
| 6   | Replay/durability test          | `test_service_replays_history_on_init` (unit) and `test_replay_restores_readiness_after_restart` (integration) both cover restart-from-disk.                                                              |
| 7   | Contract test                   | `test_required_fields_contract_matches_integration_spec` parses spec YAML and asserts parity with `_REQUIRED_FIELDS`.                                                                                     |
| 8   | `ingest_raw()` untested         | `test_service_ingest_raw_accepts_valid_event_type` and `test_service_ingest_raw_rejects_unknown_event_type` cover both paths.                                                                             |
| 9   | Missing public exports          | `ReachabilityChecker` and `IntegratedChecker` in `__init__.py` imports and `__all__`. Test `test_public_api_exports_checker_type_aliases` verifies.                                                       |

## Paradigm-Fit Assessment (Round 2)

1. **Data flow:** Domain-core pattern confirmed. All types are domain-level with no transport or UI coupling. File-backed persistence behind a clean store abstraction. Boundary purity maintained.
2. **Component reuse:** No copy-paste duplication detected. Round 1 duplication (Important #4) resolved.
3. **Pattern consistency:** Frozen dataclasses for immutable domain objects, TypedDict for serialization contracts, Literal types for closed sets, explicit validation at boundaries. Naming is domain-semantic throughout.

## Contract Fidelity (FR1)

Re-verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly (4 fields)
- `finalize_ready` fields: match exactly (6 fields)
- `branch_pushed` fields: match exactly (5 fields)
- Readiness predicate conditions 1-6: all implemented in `_recompute()`
- `worktree dirty -> clean` correctly excluded
- Contract regression test `test_required_fields_contract_matches_integration_spec` guards future drift

## Requirements Trace

| Requirement                       | Implementation                                                                 | Test Coverage                                                                                                                                      |
| --------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1: Event payload fidelity       | `events.py`: typed payloads, `_REQUIRED_FIELDS`, `validate_event_payload()`    | `test_validate_event_payload_rejects_missing_and_unexpected_fields`, `test_required_fields_contract_matches_integration_spec`                      |
| FR2: Durable idempotent ingestion | `event_store.py`: append with fsync, idempotency key check                     | `test_event_store_append_is_idempotent_and_collision_safe`, `test_service_replays_history_on_init`, `test_replay_restores_readiness_after_restart` |
| FR3: Readiness projection         | `readiness_projection.py`: `_recompute()` with all 6 predicate conditions      | `test_candidate_transitions_from_not_ready_to_ready` (integration)                                                                                 |
| FR4: Supersession semantics       | `readiness_projection.py`: `supersession_rank()`, `latest_by_slug`, `>=` check | `test_service_marks_older_finalize_candidate_as_superseded`, `test_service_breaks_equal_ready_at_ties_deterministically`                           |

## Build Verification

- `make test`: 2307 passed, 106 skipped, 0 failed (9.09s)
- `make lint`: 0 errors, 0 warnings, 0 informations
- `pyright`: clean

## Critical

(none)

## Important

(none — all round 1 findings resolved)

## Suggestions (carried from round 1, non-blocking)

### S1. `event_id` whitespace inconsistency

`build_integration_event` doesn't strip `event_id` before the empty check, but `integration_event_from_record` does. Minor inconsistency — only affects callers passing whitespace-only `event_id` strings directly.

### S2. Redundant diagnostics for missing fields

When a field is missing, both `_validate_field_set` and `_as_non_empty_str` report the same root cause, producing duplicate messages. Cosmetic — does not affect correctness.

### S3. No diagnostic for mismatched-remote `branch_pushed`

A push with `remote="upstream"` is silently ignored when the projection expects `remote="origin"`. An explicit diagnostic would aid operator debugging.

## Why No Issues (Zero-Finding Justification)

1. **Paradigm-fit verification:** Traced data flow through `events.py → event_store.py → readiness_projection.py → service.py`. All types are domain-level. No transport coupling. Store abstraction provides clean persistence boundary. Reachability/integrated checks are injected as Callable protocols — no infrastructure coupling in domain logic.
2. **Requirements validation:** Each of FR1-FR4 was traced to specific implementation code and test coverage (see Requirements Trace table above). All verification requirements (VR1-VR3) have corresponding tests.
3. **Copy-paste duplication check:** Searched for duplicated logic across the 4 source files. The round 1 duplication (`_event_digest` vs `compute_idempotency_key`) has been resolved. No new duplication found.

## Verdict: APPROVE

**Rationale:**

All 9 Important findings from round 1 have been properly resolved with corresponding commits and test coverage. Requirements FR1-FR4 are fully implemented and tested. Contract tests guard spec drift. Build is clean (tests pass, lint clean, pyright clean). No new Important or Critical findings identified.

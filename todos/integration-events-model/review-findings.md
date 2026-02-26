# Review Findings: integration-events-model

**Review round:** 2
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 13 changed files, 1535 insertions

## Paradigm-Fit Assessment

1. **Data flow:** Implementation follows the established domain-core pattern. All types are domain-level (`IntegrationEvent`, `CandidateReadiness`, etc.) with no transport or UI coupling. File-backed persistence is behind a clean store abstraction. Boundary purity is maintained.
2. **Component reuse:** No copy-paste of existing codebase components detected. The round-1 `_event_digest` duplication was eliminated (fix #4).
3. **Pattern consistency:** Follows project conventions: frozen dataclasses for immutable domain objects, TypedDict for serialization contracts, Literal types for closed sets, explicit validation at boundaries. Naming is domain-semantic.

## Contract Fidelity (FR1)

Verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly
- `finalize_ready` fields: match exactly
- `branch_pushed` fields: match exactly
- Readiness predicate conditions 1-6: all implemented in `_recompute()`
- `worktree dirty -> clean` correctly excluded (not referenced anywhere)
- Contract parity test (`test_required_fields_contract_matches_integration_spec`) guards against spec drift

## Round 1 Fix Verification (all 9 fixes confirmed)

| #   | Issue                                | Fix                                                                               | Evidence                                                                                                 |
| --- | ------------------------------------ | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| 1   | Supersession tie-break undefined     | `supersession_rank()` with `(ready_at, branch, sha)` + `>=` in supersession check | `readiness_projection.py:56-58,166,173` + `test_service_breaks_equal_ready_at_ties_deterministically`    |
| 2   | No auto-replay on init               | `self.replay()` in `__init__`                                                     | `service.py:47` + `test_service_replays_history_on_init`                                                 |
| 3   | Wrong event_type in timestamp errors | `_normalize_iso8601` accepts `event_type` as first param                          | `events.py:306` + `test_build_event_reports_correct_event_type_for_received_at_validation`               |
| 4   | Duplicate digest function            | Store imports and calls `compute_idempotency_key`                                 | `event_store.py:14,55,108`                                                                               |
| 5   | Type narrowing gap                   | `cast(str, ...)` after guard block                                                | `events.py:200-202`                                                                                      |
| 6   | Missing replay/durability test       | Unit + integration restart tests                                                  | `test_service_replays_history_on_init`, `test_replay_restores_readiness_after_restart`                   |
| 7   | Missing contract tests               | Spec YAML parity assertion                                                        | `test_required_fields_contract_matches_integration_spec`                                                 |
| 8   | `ingest_raw()` untested              | Accepted + rejected test paths                                                    | `test_service_ingest_raw_accepts_valid_event_type`, `test_service_ingest_raw_rejects_unknown_event_type` |
| 9   | Checker aliases not exported         | Added to `__init__.py` imports and `__all__`                                      | `__init__.py:18-19,48-49` + `test_public_api_exports_checker_type_aliases`                               |

## Critical

(none)

## Important

(none)

## Suggestions

### S1. `_TIMESTAMP_FIELDS` is dead code

**File:** `teleclaude/core/integration/events.py:67-69`

`_TIMESTAMP_FIELDS` is defined but never referenced anywhere in the codebase. Remove it or use it.

### S2. `event_id` whitespace asymmetry (carried from round 1)

`build_integration_event` (line 130) doesn't strip `event_id` before the empty check, but `integration_event_from_record` (line 189) does. An `event_id=" "` would pass the build path.

### S3. Redundant diagnostics for missing fields (carried from round 1)

When a field is missing, both `_validate_field_set` and `_as_non_empty_str` report the same root cause, producing duplicate messages.

### S4. No diagnostic for mismatched-remote `branch_pushed` (carried from round 1)

A push with `remote="upstream"` is silently ignored when the projection expects `remote="origin"`. An explicit diagnostic would aid operator debugging.

### S5. Unrelated `test_discord_adapter.py` change (carried from round 1)

The mock addition at line 807-808 is orthogonal to this feature and would be cleaner in a separate commit.

## Why No Issues

1. **Paradigm-fit verification:** Checked data flow (domain-only types, no transport coupling), component reuse (no copy-paste, digest duplication resolved), pattern consistency (frozen dataclasses, TypedDicts, Literal types, explicit boundary validation). All conform to project conventions.
2. **Requirements validation:** FR1 verified by tracing `_REQUIRED_FIELDS` against spec YAML and confirming all 6 readiness predicate conditions in `_recompute()`. FR2 verified by tracing `append()` → fsync → in-memory update + auto-replay in constructor. FR3 verified by walking all 6 predicate checks in `_recompute()`. FR4 verified by tracing `supersession_rank()` with `>=` comparison ensuring single-winner invariant.
3. **Copy-paste duplication check:** No duplication found. The round-1 `_event_digest` / `compute_idempotency_key` duplication was eliminated.
4. **Test coverage:** 12 unit tests + 2 integration tests covering validation, idempotency, collision, supersession, tie-breaking, replay/restart, contract parity, ingest_raw, and public API exports. All pass (2309 total suite, 0 failures). Pyright: 0 errors. Ruff: clean.

## Verification Evidence

- `make test`: 2309 passed, 106 skipped, 0 failures (9.15s)
- `make lint`: ruff format clean (320 files), ruff check passed, pyright 0 errors
- All implementation-plan tasks checked `[x]` in committed state
- Build gates all checked in committed state

## Verdict: APPROVE

**Rationale:** All 9 round-1 Important findings have been resolved with corresponding code fixes and regression tests. No new Critical or Important issues found. Contract fidelity, durability, idempotency, readiness projection, and supersession semantics all verified against spec. Test suite passes cleanly with adequate coverage across unit and integration layers. Type checker reports zero errors. Remaining suggestions are non-blocking quality improvements.

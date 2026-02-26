# Review Findings: integration-events-model

**Review round:** 1
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 9 changed files, 1143 insertions

## Paradigm-Fit Assessment

1. **Data flow:** Implementation follows the established domain-core pattern. All types are domain-level (`IntegrationEvent`, `CandidateReadiness`, etc.) with no transport or UI coupling. File-backed persistence is behind a clean store abstraction. Boundary purity is maintained.
2. **Component reuse:** No copy-paste of existing codebase components detected. The `_event_digest` / `compute_idempotency_key` duplication is internal to this feature (see Important #4).
3. **Pattern consistency:** Follows project conventions: frozen dataclasses for immutable domain objects, TypedDict for serialization contracts, Literal types for closed sets, explicit validation at boundaries. Naming is domain-semantic.

## Contract Fidelity (FR1)

Verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly
- `finalize_ready` fields: match exactly
- `branch_pushed` fields: match exactly
- Readiness predicate conditions 1-6: all implemented in `_recompute()`
- `worktree dirty -> clean` correctly excluded (not referenced anywhere)

## Important

### 1. Supersession tie-breaking undefined for equal `ready_at` timestamps

**File:** `teleclaude/core/integration/readiness_projection.py:159-163,169`

Two `finalize_ready` events for the same slug with identical `ready_at` timestamps (within the same second, since normalization uses `timespec="seconds"`) both remain active. Neither is marked `SUPERSEDED`.

The `latest_by_slug` selection uses strict `>` (line 162), so the first-inserted candidate wins the tie. The supersession check (line 169) also uses strict `>`, so the other candidate is not superseded. Result: two `READY` candidates for the same slug, violating FR4's single-winner invariant.

**Fix:** Use `>=` in the supersession check (line 169) and add a deterministic secondary tie-break key (e.g., lexicographic `(branch, sha)`) in the `latest_by_slug` selection (line 162).

### 2. No guard or auto-replay on service initialization

**File:** `teleclaude/core/integration/service.py:42-68`

`IntegrationEventService.__init__` (and `with_file_store`) does not call `replay()`. The store lazy-loads events from disk, but the projection stays empty until `replay()` is explicitly called. If a caller ingests new events without calling `replay()` first, the projection only reflects the new event — not the durable history.

This means `get_candidate()` and `all_candidates()` return silently wrong results after a restart if the caller forgets to call `replay()`.

**Fix:** Either auto-replay in the constructor, or add a `_replayed` guard that raises on read operations before `replay()` is called, or document the constraint with an explicit protocol note.

### 3. `_normalize_iso8601` misattributes `event_type` in validation errors

**File:** `teleclaude/core/integration/events.py:300-310`

`_normalize_iso8601` raises `IntegrationEventValidationError(field_name, [...])`, passing a field name (e.g., `"received_at"`) where the constructor expects an event type. When the error propagates from `build_integration_event` (line 127), `exc.event_type` will be `"received_at"` instead of the actual event type.

**Fix:** Accept the event type as a parameter to `_normalize_iso8601`, or catch and re-raise with the correct event type in `build_integration_event`.

### 4. `_event_digest` duplicates `compute_idempotency_key`

**File:** `teleclaude/core/integration/event_store.py:119-126` vs `events.py:103-111`

Both functions compute an identical SHA-256 hash from `{"event_type": ..., "payload": ...}` with the same JSON serialization settings. The store should import and call `compute_idempotency_key(event.event_type, event.payload)` instead.

### 5. `integration_event_from_record` type narrowing gap

**File:** `teleclaude/core/integration/events.py:188-206`

Variables `event_id`, `received_at`, `idempotency_key` retain `object | None` type after isinstance checks (the checks append diagnostics but don't reassign). After the guard, they're passed to `build_integration_event` expecting `str | None`. Correct at runtime due to the diagnostic guard, but would fail strict mypy/pyright.

**Fix:** Use `cast(str, ...)` after the guard or restructure with early assignment.

### 6. Missing test coverage for replay/durability path (FR2)

**File:** `tests/unit/test_integration_events_model.py`, `tests/integration/test_integration_readiness_projection.py`

Neither test file covers the restart scenario: ingest events, construct a NEW service instance on the same event log, call `replay()`, and verify readiness state is restored. This is the core durability claim of FR2 and has no regression coverage.

### 7. Missing contract tests (Verification Requirement #3)

**File:** `todos/integration-events-model/requirements.md` — VR3

The requirements explicitly state: "Contract tests asserting payload fields match spec." No test asserts that the `_REQUIRED_FIELDS` mapping matches the spec's `required_event_fields` YAML. If the spec evolves and the code doesn't track, there is no regression guard.

### 8. `service.ingest_raw()` untested

**File:** `teleclaude/core/integration/service.py:71-85`

The public boundary entry point for raw (string) event types is never exercised through any test. This is the path external callers will use.

### 9. `ReachabilityChecker` and `IntegratedChecker` missing from public API

**File:** `teleclaude/core/integration/__init__.py`

These Callable type aliases are required by any caller constructing an `IntegrationEventService` (via `with_file_store`) or `ReadinessProjection`, but they are not exported in `__all__`. Consumers must reach into `readiness_projection` directly to import them.

**Fix:** Add both to `__init__.py` imports and `__all__`.

## Suggestions

### S1. `event_id` whitespace inconsistency

`build_integration_event` (line 130) doesn't strip `event_id` before the empty check, but `integration_event_from_record` (line 189) does. An `event_id=" "` would pass the build path.

### S2. Redundant diagnostics for missing fields

When a field is missing, both `_validate_field_set` ("missing required fields: ['slug']") and `_as_non_empty_str` ("slug must be a non-empty string") report the same root cause, producing duplicate messages.

### S3. No diagnostic for mismatched-remote `branch_pushed`

A push with `remote="upstream"` is silently ignored when the projection expects `remote="origin"`. An explicit diagnostic would aid operator debugging.

### S4. Unrelated `test_discord_adapter.py` change

The mock addition at line 807-808 is orthogonal to this feature and would be cleaner in a separate commit.

## Verdict: REQUEST CHANGES

**Rationale:**

- Important #1 (supersession tie-break) is a logic defect in FR4 that can produce two READY candidates for the same slug.
- Important #6-8 (test coverage) leave FR2 durability untested and Verification Requirement #3 (contract tests) unmet.
- Important #2 (no replay guard) creates a silent failure path for warm-start consumers.
- Important #9 (missing public exports) blocks external consumers from type-safe construction.

## Fixes Applied

- Important #1: deterministic supersession ordering with equal `ready_at` timestamps plus tie regression test. Commit: `cd0a19c6`
- Important #2: replay durable history during `IntegrationEventService` initialization with restart coverage. Commit: `f4dd8a8b`
- Important #3: pass canonical event type through ISO8601 normalization errors with attribution test. Commit: `ab5697db`
- Important #4: remove duplicate event digest implementation and reuse `compute_idempotency_key`. Commit: `7e95d517`
- Important #5: explicitly narrow persisted record identifiers to `str` before build path, with deserialize coverage. Commit: `efa9cd04`
- Important #6: add integration replay/durability restart test calling `replay()` on a new service instance. Commit: `b713bfdd`
- Important #7: add contract test asserting `_REQUIRED_FIELDS` parity with spec YAML `required_event_fields`. Commit: `76261828`
- Important #8: add unit coverage for `service.ingest_raw()` accepted and rejected raw event types. Commit: `02dfcbe6`
- Important #9: export `ReachabilityChecker` and `IntegratedChecker` from package public API, with export-surface test. Commit: `2bc35e06`

---

## Round 2: Verification Review

**Review round:** 2
**Scope:** Verify all 9 round 1 fixes and scan for regressions.

### Round 1 Fix Verification

All 9 Important fixes from round 1 verified against the current code:

| #   | Finding                         | Verification                                                                                                                                                                                                                                                                                         |
| --- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Supersession tie-breaking       | `supersession_rank()` returns `(ready_at, branch, sha)` for deterministic ordering. `>=` on line 173, `>` on line 166. Exact rank ties are impossible for distinct candidates (same slug+branch+sha = same CandidateKey). Test `test_service_breaks_equal_ready_at_ties_deterministically` confirms. |
| 2   | Auto-replay on init             | `service.py:47` calls `self.replay()` in `__init__`. Test `test_service_replays_history_on_init` verifies state restored without explicit replay.                                                                                                                                                    |
| 3   | `_normalize_iso8601` event_type | `events.py:306` accepts `event_type: IntegrationEventType` as first param. Both call sites (`build_integration_event:126`, `_as_iso8601:300`) pass it correctly. Test asserts `exc.value.event_type == "review_approved"`.                                                                           |
| 4   | Duplicate `_event_digest`       | `event_store.py:14` imports `compute_idempotency_key`. No local duplicate exists. Lines 55 and 108 use the canonical function.                                                                                                                                                                       |
| 5   | Type narrowing with `cast`      | `events.py:200-202` uses `cast(str, ...)` after the diagnostic guard at lines 188-198. Type-safe for strict checkers. Test `test_integration_event_from_record_accepts_valid_string_fields` covers.                                                                                                  |
| 6   | Replay/durability test          | Unit: `test_service_replays_history_on_init`. Integration: `test_replay_restores_readiness_after_restart`. Both create a new service on the same event log and verify state.                                                                                                                         |
| 7   | Contract test                   | `test_required_fields_contract_matches_integration_spec` loads spec YAML, parses `required_event_fields`, and asserts parity with `_REQUIRED_FIELDS`.                                                                                                                                                |
| 8   | `ingest_raw` tests              | `test_service_ingest_raw_accepts_valid_event_type` and `test_service_ingest_raw_rejects_unknown_event_type` cover both paths.                                                                                                                                                                        |
| 9   | Public API exports              | `__init__.py` imports and exports `ReachabilityChecker` and `IntegratedChecker` in `__all__`. Test `test_public_api_exports_checker_type_aliases` asserts.                                                                                                                                           |

### Paradigm-Fit Assessment (Round 2)

1. **Data flow:** Domain-core pattern preserved through all fixes. No transport or UI coupling introduced.
2. **Component reuse:** `_event_digest` duplication eliminated (fix #4). No new duplication.
3. **Pattern consistency:** All fixes follow existing conventions (frozen dataclasses, cast for narrowing, canonical function reuse).

### Why No Important or Higher Findings

1. **Paradigm-fit verified:** All fixes follow domain-core conventions — frozen dataclasses, TypedDict contracts, explicit validation at boundaries. No adapter coupling introduced.
2. **Requirements validated:** FR1 (contract fidelity confirmed against spec YAML), FR2 (idempotency + durability both tested including restart), FR3 (readiness predicates in `_recompute()` match spec's 6 conditions), FR4 (supersession with deterministic tie-breaking, single-winner invariant proven by construction).
3. **Copy-paste checked:** Fix #4 eliminated the only duplication. No new duplications introduced.

### Suggestions (Non-Blocking)

#### S5. `_ensure_loaded` does not skip genuine duplicate records

**File:** `teleclaude/core/integration/event_store.py:108-115`

If the event log contains a line duplicated by external means (crash-recovery, backup restore), `_ensure_loaded` appends the event to `self._events` twice. Under normal operation `append()` prevents this, and `ReadinessProjection.replay()` is idempotent (reset + re-apply), so correctness is not affected. Defensive hardening: add `continue` when `existing_digest is not None and existing_digest == event_digest`.

#### S6. Contract test regex matches first YAML block only

**File:** `tests/unit/test_integration_events_model.py:99`

`re.search(r"```yaml\n(.*?)\n```", ...)` selects the first YAML fence in the spec. If a second block is added above the machine-readable surface, the test silently parses the wrong block. Consider anchoring to the section heading.

#### S7. Integration replay test calls `replay()` redundantly

**File:** `tests/integration/test_integration_readiness_projection.py:137`

`IntegrationEventService.__init__` already calls `self.replay()`. The explicit `restarted.replay()` call means the test would pass even if the auto-replay were broken. The parallel unit test (`test_service_replays_history_on_init`) correctly omits this. Non-blocking since the unit test covers the invariant.

#### S8. `_as_positive_int` accepts `bool` values

**File:** `teleclaude/core/integration/events.py:282-289`

`isinstance(True, int)` is `True` in Python. `review_round=True` would pass validation and be stored. Low practical risk (internal agents produce typed payloads), but an `isinstance(raw, bool)` guard before the int check would close the gap.

#### S9. No test for reachability/integrated checker blocking paths

**File:** `tests/integration/test_integration_readiness_projection.py`

All tests use permissive checker stubs. No test verifies that `reachability_checker=False` or `integrated_checker=True` blocks readiness. The predicates are straightforward conditionals in `_recompute()` lines 195-199. Low regression risk but explicit coverage would strengthen FR3 verification.

### Round 1 suggestions S1-S4 status

- **S1 (`event_id` whitespace):** Still present, unchanged.
- **S2 (Redundant diagnostics):** Still present, unchanged.
- **S3 (No mismatched-remote diagnostic):** Still present, unchanged.
- **S4 (Unrelated `test_discord_adapter.py` change):** Still present, unchanged.

## Verdict: APPROVE

**Rationale:**

All 9 round 1 Important findings are correctly fixed with tests. No new Important or Critical issues found. The implementation satisfies FR1-FR4, all three Verification Requirements are covered, and the code follows established domain-core patterns. Suggestions S5-S9 are non-blocking improvements for future hardening.

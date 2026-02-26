# Review Findings: integration-events-model

**Review round:** 3
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 9 changed files, 1143 insertions
**Previous verdict:** REQUEST CHANGES (round 1) — 9 Important findings
**Tests:** 2311 passed, 106 skipped (9.67s) — `make test` clean
**Lint:** ruff + pyright 0 errors — `make lint` clean

## Paradigm-Fit Assessment

1. **Data flow:** Implementation follows the established domain-core pattern. All types are domain-level (`IntegrationEvent`, `CandidateReadiness`, etc.) with no transport or UI coupling. File-backed persistence is behind a clean store abstraction. Boundary purity is maintained.
2. **Component reuse:** No copy-paste of existing codebase components detected. The former `_event_digest` / `compute_idempotency_key` duplication was resolved (Fix #4).
3. **Pattern consistency:** Follows project conventions: frozen dataclasses for immutable domain objects, TypedDict for serialization contracts, Literal types for closed sets, explicit validation at boundaries. Naming is domain-semantic.

## Contract Fidelity (FR1)

Verified against `docs/project/spec/integration-orchestrator.md`:

- `review_approved` fields: match exactly
- `finalize_ready` fields: match exactly
- `branch_pushed` fields: match exactly
- Readiness predicate conditions 1-6: all implemented in `_recompute()`
- `worktree dirty -> clean` correctly excluded (not referenced anywhere)
- Contract test `test_required_fields_contract_matches_integration_spec` validates `_REQUIRED_FIELDS` against spec YAML

## Verification of Round 1 Fixes (All 9 Confirmed)

| #   | Issue                                         | Fix                                                                                        | Verified |
| --- | --------------------------------------------- | ------------------------------------------------------------------------------------------ | -------- |
| 1   | Supersession tie-break undefined              | `supersession_rank()` returns `(ready_at, branch, sha)`; `>=` comparison in `_recompute()` | Yes      |
| 2   | No auto-replay on init                        | `service.py:47` — `self.replay()` in `__init__`                                            | Yes      |
| 3   | `_normalize_iso8601` misattributed event type | `events.py:306` — accepts `event_type` parameter                                           | Yes      |
| 4   | Duplicate digest                              | `event_store.py:55` — calls `compute_idempotency_key`                                      | Yes      |
| 5   | Type narrowing gap in `from_record`           | `events.py:200-202` — `cast(str, ...)` after guard                                         | Yes      |
| 6   | Missing replay/durability test                | `test_service_replays_history_on_init` — no explicit `replay()`                            | Yes      |
| 7   | Missing contract tests (VR3)                  | `test_required_fields_contract_matches_integration_spec` parses spec YAML                  | Yes      |
| 8   | `ingest_raw()` untested                       | Two tests: accepted and rejected raw event type paths                                      | Yes      |
| 9   | Checker aliases missing from `__all__`        | Both in `__init__.py` imports and `__all__`                                                | Yes      |

## Requirement Coverage Trace

| Requirement                               | Evidence                                                                                             |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| FR1.1 — Fields match spec                 | Contract test + manual spec comparison                                                               |
| FR1.2 — Missing fields rejected           | `test_validate_event_payload_rejects_missing_and_unexpected_fields`                                  |
| FR2.1 — Persist before projection         | Code: `store.append()` then `projection.apply()` in `service.py:117-124`                             |
| FR2.2 — Duplicate idempotency             | `test_event_store_append_is_idempotent_and_collision_safe`                                           |
| FR3.1 — All three events required         | `test_candidate_transitions_from_not_ready_to_ready`                                                 |
| FR3.2 — Reachability + not-integrated     | Covered via lambda stubs in projection tests                                                         |
| FR3.3 — `worktree dirty → clean` excluded | Not defined as event type; `parse_event_type` rejects unknown types                                  |
| FR4.1 — Newer finalize supersedes         | `test_service_marks_older_finalize_candidate_as_superseded`                                          |
| FR4.2 — Superseded remain auditable       | Same test: `old_candidate.status == "SUPERSEDED"` still retrievable                                  |
| VR1 — Unit tests                          | 12 unit tests covering validation, idempotency, supersession, tie-break, replay, ingest_raw, exports |
| VR2 — Integration test NOT_READY → READY  | `test_candidate_transitions_from_not_ready_to_ready`                                                 |
| VR3 — Contract tests                      | `test_required_fields_contract_matches_integration_spec`                                             |

## Why No Important/Critical Issues

1. **Paradigm-fit verified:** All domain types are pure (frozen dataclasses, TypedDicts). No transport coupling. Store abstraction is clean. Projection recomputation is side-effect-free.
2. **Requirements verified:** Every FR1-FR4 and VR1-VR3 requirement has implementation evidence and test coverage. Coverage trace above.
3. **Copy-paste checked:** No duplicate components found. The round 1 digest duplication was resolved.
4. **All 9 prior fixes verified:** Each fix addresses the original finding correctly, with regression tests where applicable.

## Suggestions

### S1. Integration test has redundant `replay()` call

**File:** `tests/integration/test_integration_readiness_projection.py:137`

`restarted.replay()` is called explicitly after construction, but `__init__` already auto-replays. The explicit call is a leftover from before Fix #2. The unit test `test_service_replays_history_on_init` correctly guards the auto-replay invariant without an explicit call. Removing line 137 would make the integration test consistent and a better regression guard.

### S2. `_as_positive_int` accepts `bool` as int

**File:** `teleclaude/core/integration/events.py:282`

`isinstance(True, int)` is `True` in Python, so `review_round: True` would pass validation. Edge case — internal callers pass integers. Adding `or isinstance(raw, bool)` to the guard would close the gap.

### S3. `event_id` whitespace inconsistency (carried from round 1 S1)

**File:** `teleclaude/core/integration/events.py:130`

`build_integration_event` does not strip `event_id` before the empty check, while `integration_event_from_record` does. `event_id=" "` would be stored via build but rejected on deserialization. Adding `.strip()` to the build path would close the asymmetry.

### S4. Build Gates checklist reset by merge

The committed quality checklist Build Gates are `[ ]` due to merge `4a01182c` overwriting commit `2229172c` which had them all `[x]`. The actual build evidence (tests, lint, pyright, state.yaml `build: complete`) is valid.

## Verdict: APPROVE

**Rationale:**

- All 9 round 1 Important findings are correctly fixed and verified with evidence.
- Contract fidelity confirmed: `_REQUIRED_FIELDS` matches spec YAML, readiness predicate conditions 1-6 implemented, `worktree dirty → clean` excluded.
- Tests pass (2311), lint clean (ruff + pyright 0 errors).
- All FR1-FR4 requirements traced to implementation and test coverage.
- No Important or Critical issues found in round 3. Four suggestions noted for future improvement.

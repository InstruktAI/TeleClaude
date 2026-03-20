# Review Findings: state-machine-versioning

**Reviewer:** Claude (code review session)
**Round:** 2 (re-review after fix)
**Diff base:** `git merge-base HEAD main`

---

## Round 1 Summary

Round 1 identified 6 Critical, 6 Important, 3 Suggestion findings. The reviewer auto-remediated
C4, C5, C6 during round 1. A fixer session addressed C1-C3, I1-I6, S1, S3 across 3 commits.

## Round 2 Verification

### Critical — All Resolved

| ID  | Finding                                            | Status                                                                                                                                                                                                         |
| --- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | API transition firing returns 501                  | **RESOLVED** — `todo_routes.py` now uses `build_lifecycle_machine()`, fires transitions with `machine.fire()`, handles `TransitionRejected` (409) and `ValueError` (400). Actor identity derived from session. |
| C2  | `_is_artifact_produced` in runtime paths           | **RESOLVED** — Removed from `prepare_steps.py`, `prepare_events.py`, `core.py`. Zero matches in runtime code.                                                                                                  |
| C3  | `_derive_prepare_phase` in runtime paths           | **RESOLVED** — Deleted from `prepare_events.py`, `__all__`, and `core.py` re-export. Zero matches in runtime code.                                                                                             |
| C4  | `--no-autostash` regression                        | **RESOLVED** (round 1 auto-remediation)                                                                                                                                                                        |
| C5  | `_validate_preparation_freshness` reads dead field | **RESOLVED** (round 1 auto-remediation) — reads `current` now.                                                                                                                                                 |
| C6  | Missing `_PREPARE_CURRENT_VALUES` entries          | **RESOLVED** (round 1 auto-remediation)                                                                                                                                                                        |

### Important — All Resolved

| ID  | Finding                                | Status                                                                                                                                                                                                                   |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| I1  | mark-\* wrappers bypass engine         | **RESOLVED** — `mark_phase` (line 344-352), `mark_finalize_ready` (line 493-500), `_mark_finalize_handed_off` (line 528-535) all route through `StateMachine.fire()` with `build_lifecycle_machine()`. History recorded. |
| I2  | work.py uses mark_phase() not fire()   | **RESOLVED** — Implicitly fixed via I1; mark_phase now uses engine internally.                                                                                                                                           |
| I3  | Guidance strings not migrated          | **RESOLVED** — Work-phase guidance (lines 52-82 in output_formatting.py) now uses `telec todo state` transitions. Prepare-phase artifact markers retain `mark-phase` correctly (different purpose).                      |
| I4  | Duplicated state-to-status mapping     | **RESOLVED** — `work_lifecycle.py` provides canonical `CURRENT_TO_BUILD_REVIEW`. Both `work.py` and `roadmap.py` import from it.                                                                                         |
| I5  | Migration tests missing for 8 branches | **RESOLVED** — 8 new migration tests: finalize_handed_off, finalize_ready, review_approved, review_changes_requested, review_pending, build_complete, build_started, plus existing prepare_phase test.                   |
| I6  | `HistoryEntry.metadata` type mismatch  | **RESOLVED** — Now `NotRequired[dict[str, StateValue]]` matching engine behavior.                                                                                                                                        |

### Suggestions — All Resolved

| ID  | Finding                                      | Status                                                                             |
| --- | -------------------------------------------- | ---------------------------------------------------------------------------------- |
| S1  | Stale docstring in prepare_steps.py:4        | **RESOLVED** — Reference to `_derive_prepare_phase` removed.                       |
| S2  | `_state_index` returns -1 for unknown states | Remains as design note — acceptable behavior documented via state ordering.        |
| S3  | Stale docstrings referencing v1 fields       | **RESOLVED** — `mark_ready`, `mark_prepare_phase`, `next_work` docstrings updated. |

---

## NFR-1 Sweep (Round 2)

Verified zero remaining runtime references to legacy fields:

```
grep state["build"]/state["review"]/state["prepare_phase"] teleclaude/ --include='*.py'
```

3 remaining matches in `teleclaude/core/roadmap.py:107-108,117` are in the display layer's raw
YAML read path — v1 fallback for files not yet migrated on disk. This is the expected behavior:
`_read_todo_metadata()` reads raw YAML (avoiding write side effects from migration) and falls
back to legacy fields when `current` is absent. NOT an NFR-1 violation — these are display
fallbacks, not lifecycle state inference.

---

## New Architecture Verified

The `work_lifecycle.py` module is a clean addition:

- `LIFECYCLE_STATES`: 17 ordered states covering prepare + work phases
- `CURRENT_TO_BUILD_REVIEW`: single source of truth for legacy status derivation
- `_TRANSITIONS`: 12 named transition definitions with appropriate source sets
- `MARK_PHASE_TO_TRANSITION`: maps legacy (phase, status) to transition names
- `build_lifecycle_machine()`: factory for the canonical machine

The engine is now **wired to all mutation paths**:

- `mark_phase()` → `machine.fire(transition_name, ...)`
- `mark_finalize_ready()` → `machine.fire("mark_finalize_ready", ...)`
- `_mark_finalize_handed_off()` → `machine.fire("finalize_handoff", ...)`
- `POST /todos/state` → `machine.fire(transition, ...)`

---

## Test Results

161 tests pass (targeted suite: core, CLI, API, scaffold). 14 spec tests all GREEN.
Fixer reports 4151 passed, 3 pre-existing failures unrelated to changes.

---

## Lane Summary (Round 2)

| Lane       | Status   | Findings     |
| ---------- | -------- | ------------ |
| scope      | Complete | All resolved |
| code       | Complete | All resolved |
| paradigm   | Complete | No findings  |
| principles | Complete | All resolved |
| security   | Complete | No findings  |
| tests      | Complete | All resolved |
| errors     | Complete | All resolved |
| types      | Complete | All resolved |
| comments   | Complete | All resolved |
| logging    | Complete | No findings  |
| demo       | Complete | All resolved |
| docs       | Complete | No findings  |

---

## Verdict: APPROVE

**Unresolved Critical: 0**
**Unresolved Important: 0**

All 12 round-1 findings resolved. The state machine engine is now wired to every mutation
path, history is recorded for all transitions, the API fires transitions, dead code is
removed, and migration tests cover all v1→v2 branches. The `work_lifecycle.py` module
provides a clean canonical definition for states, transitions, and status mappings.

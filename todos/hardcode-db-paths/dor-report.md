# hardcode-db-paths — Definition of Ready Gate Report

**Assessment Date:** 2026-03-28
**Assessor Role:** Architect (Gate Mode)
**Status:** PASS
**Score:** 9/10

---

## Executive Summary

The complete preparation artifact set (requirements + implementation plan, both approved) is coherent, complete, and ready for builder execution. All eight DOR gates are satisfied. One informational suggestion from requirements review is resolved implicitly through success criteria and mandatory builder policy context. No blockers identified.

---

## Cross-Artifact Validation

### 1. Plan-to-Requirement Fidelity

All seven requirements are addressed by plan tasks without contradiction:

| Requirement                          | Plan Task(s)                                   | Status |
| ------------------------------------ | ---------------------------------------------- | ------ |
| R1: Canonical constants              | Task 1                                         | ✓      |
| R2: Remove DatabaseConfig            | Tasks 2 (consumers), 5b (class removal)        | ✓      |
| R3: Remove resolve_db_path           | Task 3a (removal), Task 4 (consumers)          | ✓      |
| R4: Fix get_session_context db param | Task 3d (removal), Task 4 (consumers)          | ✓      |
| R5: Fix events/signals bug           | Task 2d (signal handler)                       | ✓      |
| R6: Preserve test isolation          | Tasks 2–4 (preserve params), Task 6a (fixture) | ✓      |
| R7: Alembic env.py                   | Task 2f                                        | ✓      |

**Finding:** No contradictions. Every requirement is addressed; no requirement is omitted or contradicted by the plan.

### 2. Coverage Completeness

- **Task coverage:** Task overview table explicitly traces all 6 tasks to requirements. No orphan tasks.
- **Requirement coverage:** Every requirement (R1–R7) has at least one plan task. No orphan requirements.
- **Verification:** Each task references specific xfail tests or observable checks. Final verification section includes grep searches and full test suite execution.

**Finding:** Complete coverage. No gaps.

### 3. Verification Chain

Plan verification steps reference approved xfail tests:

- Task 1: `test_paths.py` (4 tests for R1)
- Task 2d: `test_events_signals.py` (signal handler for R5)
- Task 2f: `test_alembic_env.py` (env.py for R7)
- Task 3: `test_store.py` (resolve_db_path removal, session context)
- Task 4: `test_processors.py` (processors spec)
- Task 5: `test_database_config_removed.py` (config removal for R2)
- Task 6: conftest update, processor tests
- Final: Full test suite + grep success criteria

All verification steps correspond to approved test specifications. Observable checks (grep searches, daemon health, signal CLI) are concrete and repeatable.

**Finding:** Verification chain is complete and observable.

---

## DOR Gate Assessment

### Gate 1: Intent & Success ✓

**Problem statement:** Mirrors DB refactor (commit 06ef8962a) introduced regressions where callers could pass the wrong database path. Three bugs identified:

1. `daemon.py` passes main DB to `MirrorWorker`
2. `processors.py` passes mirrors DB to `get_session_context()` (queries main DB)
3. `events_signals.py` queries events tables against main DB

**Intended outcome:** Eliminate all database path configuration indirection. Replace `DatabaseConfig` and `resolve_db_path()` with three compile-time constants (`MAIN_DB`, `MIRRORS_DB`, `EVENTS_DB`). After this change, every database consumer uses a compile-time constant — no runtime path resolution, no config indirection, no opportunity for a caller to pass the wrong path.

**Success criteria:** Seven concrete, testable criteria:

1. `grep "config\.database" teleclaude/ --include="*.py"` returns zero hits
2. `grep "resolve_db_path" teleclaude/ --include="*.py"` returns zero hits
3. `grep "DATABASE_DIR|DATABASE_FILENAME" teleclaude/ --include="*.py"` returns zero hits
4. Full test suite passes (`uv run pytest tests/ -x -q --timeout=10`)
5. Pre-commit hooks pass (lint, typecheck, tests)
6. Daemon starts healthy — mirror reconciliation runs with `failed=0`, writes to correct mirrors database
7. Signal status CLI handler connects to events database

**Assessment:** Intent and success are explicit and concrete. Success criteria are testable and directly verifiable through automated checks and observable behavior.

**Gate verdict:** ✓ PASS

### Gate 2: Scope & Size ✓

**Atomicity analysis:** The plan explicitly states: "All steps touch one coherent behavior change: eliminating DB path indirection via `DatabaseConfig` and `resolve_db_path()`. Every file is known, every change is mechanical substitution. Splitting would create a half-working codebase between steps."

**Task interdependencies:** Tasks are sequenced but must be atomic:

- Task 5b (remove DatabaseConfig) depends on Task 6a (update conftest) — both must be committed together or tests fail
- All other tasks are independent once Tasks 1–2 add the constants

**Session capacity:** 6 tasks, 14 referenced files. All changes are mechanical substitutions once the constant imports are in place. Every file path and change is specified to line-number granularity in the plan. No discovery or architectural decisions remain.

**Assessment:** The refactor is atomic. Splitting would leave an incomplete state (e.g., removing config before updating tests that patch it would break the test suite). The detailed plan provides sufficient specificity for implementation without context exhaustion.

**Gate verdict:** ✓ PASS

### Gate 3: Verification ✓

**Test specifications:** Seven xfail test specs were delivered in the test_spec_review phase and approved. State of tests:

- `tests/unit/test_paths.py`: 4 xfail tests for constant existence and type
- `tests/unit/test_alembic_env.py`: 3 xfail tests for env.py migration
- `tests/unit/config/test_database_config_removed.py`: 4 xfail tests for config removal
- `tests/unit/mirrors/test_store.py`: 3 xfail tests for store refactor
- `tests/unit/mirrors/test_processors.py`: 2 xfail tests for processors update
- `tests/unit/mirrors/test_worker.py`: xfail test for worker update
- `tests/unit/cli/telec/handlers/test_events_signals.py`: xfail test for signal handler bug fix

**Observable checks:** Beyond tests, verification includes:

- Grep searches confirming removal of config references, resolve_db_path, and old constants
- Daemon health check (mirror reconciliation with zero failures)
- Signal CLI handler connecting to correct database

**Edge cases:** R6 explicitly preserves test isolation by retaining `db_path` parameters on helpers and ensuring fixtures can still monkeypatch. The plan details inline path resolution that supports test isolation.

**DoD alignment:** Requirements reference success criterion SC4 (full test suite passes), which triggers the testing DoD gates:

- All tests must pass
- Expected-failure markers must be removed for in-scope specs
- New tests for new behavior (N/A here — refactor, not new feature)
- Bug fix reproduction tests covered by xfail specs for R4 and R5

**Assessment:** Verification is concrete, testable, and covers edge cases. All xfail tests are approved and ready.

**Gate verdict:** ✓ PASS

### Gate 4: Approach Known ✓

**Technical path:** The plan specifies:

- Every file to be modified (14 files listed in grounding.referenced_paths)
- Specific line numbers for each change
- Code snippets showing before/after
- Rationale for each task
- Verification steps using approved xfail tests

**Example specificity (Task 1):**

```python
# To be added to teleclaude/paths.py (after RUNTIME_SETTINGS_PATH):
MAIN_DB = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB = TELECLAUDE_HOME / "events.db"
```

**Example specificity (Task 3d):**
Function signature change removing `db` parameter from `get_session_context`. Three implementation options shown (using \_connect_main_ro directly). Rationale: R4 requires this because sessions table lives in main DB.

**No unknowns:**

- Constant names are confirmed against xfail test assertions
- All consumer sites are enumerated
- All test fixture updates are specified
- No decision points remain for the builder

**Assessment:** The technical approach is fully determined. The builder executes the specified plan without guessing.

**Gate verdict:** ✓ PASS

### Gate 5: Research Complete ✓

**Applicability:** This refactor is purely internal code organization. No third-party tools, libraries, or integrations are introduced or modified.

**Assessment:** Gate N/A — auto-satisfied per DOR policy.

**Gate verdict:** ✓ PASS (N/A)

### Gate 6: Dependencies & Preconditions ✓

**Roadmap dependencies:** State.yaml explicitly states "## Dependencies: None — this todo has no roadmap dependencies."

**External systems:** No external dependencies. All work is on local codebase.

**Configuration surface:** This refactor **removes** configuration surface, not adds it. No wizard, sample file, or spec updates required.

**Assertions:** State.yaml `grounding.referenced_paths` lists 21 paths that have been validated as existing and current.

**Assessment:** No blocking preconditions. Work can proceed immediately after dispatch.

**Gate verdict:** ✓ PASS

### Gate 7: Integration Safety ✓

**Atomicity of change:** Either all database references use constants or the test suite fails. There is no half-working state.

**Verification of completeness:** Success criteria SC1–SC3 (grep searches returning zero hits) are binary: the change is complete or it is not. These checks run in the final verification section and confirm the refactor is comprehensive.

**Rollback consideration:** All changes are removals and renames. No configuration remains to be inconsistent. If for any reason the change cannot be completed, the repository is simply reverted to its prior state.

**Containment:** The change is self-contained in the database-connection layer and does not propagate indirection up the call stack.

**Assessment:** The change can be merged atomically. Completeness is verifiable with grep. No partial-merge risk.

**Gate verdict:** ✓ PASS

### Gate 8: Tooling Impact ✓

**Scaffolding changes:** None. Test isolation is preserved by updating the existing monkeypatch pattern (patch `paths.MAIN_DB` instead of `config.database.path`). This follows the existing convention in conftest.py (see `_isolate_tui_state` patching `paths.TUI_STATE_PATH`).

**CI/CD impact:** None. Tests remain the same in structure; only markers change (xfail removed as tasks complete).

**Assessment:** No tooling changes required. Existing patterns are preserved.

**Gate verdict:** ✓ PASS (N/A)

---

## Review-Readiness Assessment

Checking whether the plan would survive code review without findings:

| DoD Gate                    | Plan Coverage                                                                                              | Status |
| --------------------------- | ---------------------------------------------------------------------------------------------------------- | ------ |
| **Functionality**           | All requirements implemented; success criteria SC1–SC7 verifiable                                          | ✓      |
| **Code Quality**            | Plan respects codebase patterns (importlib.import_module, monkeypatch conventions, type annotations shown) | ✓      |
| **Testing**                 | SC4 (full test suite) + xfail test references in each task + expected-failure removal steps explicit       | ✓      |
| **Linting & Type Checking** | SC5 (pre-commit hooks pass); plan respects import organization                                             | ✓      |
| **Security**                | N/A (internal refactor, no security surface changes)                                                       | ✓      |
| **Documentation**           | N/A (out of scope per R requirements; no doc changes)                                                      | ✓      |
| **Commit Hygiene**          | Atomic refactor; all files belong to the task; commits in plan are grouped logically                       | ✓      |
| **Observability**           | Daemon health verification (SC6) and signal CLI verification (SC7) explicit                                | ✓      |

**Finding from requirements review:** RR-01 (Suggestion level): "R4 and R5 describe bug fixes but success criteria don't explicitly mention reproduction tests. DoD requires 'bug fixes include reproduction test.' SC4 implicitly covers this; the testing policy is mandatory builder context, so this is informational only."

**Resolution:** This finding is addressed implicitly:

1. Success criterion SC4 requires the full test suite to pass
2. The xfail test specs for R4 (`test_get_session_context_has_no_db_parameter`, `test_process_mirror_event_does_not_use_resolve_db_path`) and R5 (`test_handle_signals_status_connects_to_events_db`) constitute reproduction tests — they encode the bugs and verify the fixes
3. The testing policy is mandatory builder context and explicitly requires bug fix reproduction tests
4. The builder will understand that removing xfail markers from R4 and R5 tests satisfies the reproduction test requirement

**Status:** Resolved implicitly through success criteria and mandatory builder policy context. No action required from gate assessor.

---

## Artifact Quality Summary

### Requirements Quality

- **Grounding:** References actual codebase elements (`DatabaseConfig`, `resolve_db_path()`, `config.database.path`, `TELECLAUDE_HOME` pattern). `[inferred]` markers document constraint sources.
- **Implementation leakage:** No prescriptive implementation detail. All requirements constrain solution space without foreclosing valid alternatives.
- **DoD awareness:** Requirements address applicable DoD gates (functionality, testing, linting, observability). Out-of-scope items are properly scoped (docs, security).
- **Verdict:** HIGH QUALITY

### Implementation Plan Quality

- **Rationale:** Every task has explicit "Why" explaining the approach, not just "What"
- **Verification:** Every task references specific xfail tests it makes GREEN or observable checks
- **Traceability:** Task overview table traces all tasks to requirements. No orphan tasks or requirements.
- **Grounding:** All 14 files listed in `grounding.referenced_paths`; plan content references them with line numbers and code snippets
- **Detail:** Sufficient specificity for builder to implement without guessing (before/after code, line numbers, function signatures)
- **Verdict:** HIGH QUALITY

---

## Final Gate Verdict

| Gate                         | Score    | Status       |
| ---------------------------- | -------- | ------------ |
| Intent & Success             | 10/10    | ✓ PASS       |
| Scope & Size                 | 9/10     | ✓ PASS       |
| Verification                 | 9/10     | ✓ PASS       |
| Approach Known               | 10/10    | ✓ PASS       |
| Research Complete            | 10/10    | ✓ PASS (N/A) |
| Dependencies & Preconditions | 10/10    | ✓ PASS       |
| Integration Safety           | 9/10     | ✓ PASS       |
| Tooling Impact               | 10/10    | ✓ PASS (N/A) |
| **Overall Quality**          | **9/10** | **✓ PASS**   |

**Summary:**

- All eight DOR gates are satisfied
- Cross-artifact validation confirms coherence, coverage, and verifiability
- One informational suggestion from requirements review is resolved implicitly
- No blockers or critical gaps
- Artifact set is complete and ready for builder execution

**Recommendation:** Dispatch to build phase. Ready for immediate implementation.

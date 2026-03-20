# Plan Review Findings: state-machine-versioning (Round 2)

Round 1 findings (C1: deferred scope, I1: incomplete grounding, I2: missing review-lane
coverage) have been fully addressed in the revised plan — 9 tasks now cover all 14
requirements with explicit file lists, test spec references, and a demo artifact.

## Resolved During Review

All Important findings were localized, high-confidence, and auto-remediated in this pass.

### I1: Task 7 missing DTO pipeline files (auto-remediated)

**Severity:** Important

Requirements FR-11 explicitly lists "TodoDTO/TodoInfo in api_models.py maps from v2 fields."
The plan's Task 7 did not mention `core/models/_snapshot.py` (where `TodoInfo` carries
`build_status`/`review_status`), `api_models.py` (where `TodoDTO.from_info()` maps them),
or `core/cache.py` (which reads them). The entire DTO pipeline from state -> TodoInfo ->
TodoDTO -> TUI/API was missing.

**Resolution:** Added `core/models/_snapshot.py` coverage to Task 7 with explanation of the
DTO pipeline. Noted that the simplest approach is to derive `build_status`/`review_status`
from `current` at `TodoInfo` construction time in `roadmap.py`, keeping the downstream
contract stable. Added all three files to `state.yaml` `referenced_paths`.

### I2: Task 4c missing prepare_events.py:170 write (auto-remediated)

**Severity:** Important

`prepare_events.py` line 170 writes `state["prepare_phase"]` in the grounding invalidation
function (`check_changed_paths_invalidation`). Task 4c covered removing `_derive_prepare_phase()`
and `_is_artifact_produced()` but did not address this separate write location.

**Resolution:** Added explicit mention of `prepare_events.py:170` to Task 4c with the required
substitution (`state["prepare_phase"]` -> `state["current"]`).

### I3: Missing referenced_paths in state.yaml (auto-remediated)

**Severity:** Important

`grounding.referenced_paths` did not include `teleclaude/api_models.py`,
`teleclaude/core/models/_snapshot.py`, or `teleclaude/core/cache.py` — files that the
plan now touches.

**Resolution:** Added all three paths to `state.yaml`.

### I4: Task 7 verification acknowledges test gap (auto-remediated)

**Severity:** Important

Task 7 (display/validation consumers) had no test spec references and vague manual
verification. The DoD-driven review-awareness check requires that the plan anticipate
what the code reviewer will check for test coverage.

**Resolution:** Strengthened Task 7 verification section to acknowledge that no test specs
were delivered for display consumer behavior (test spec phase covered engine, migration,
routing, readiness, and CLI only). Noted that the code reviewer should evaluate whether
additional characterization tests are warranted.

## Suggestions

### S1: Task 2 verification could name specific existing tests

Task 2 says "Existing tests that construct TodoState directly should still work" but
does not name them. Naming specific test files would strengthen traceability.

## Review Evidence

### Requirement coverage

All 12 functional requirements and 2 non-functional requirements map to plan tasks:

| Requirement                     | Task(s) |
| ------------------------------- | ------- |
| FR-1 Authoritative State Value  | 4, 5, 7 |
| FR-2 Atomic Guarded Transitions | 1       |
| FR-3 Idempotent Semantics       | 1       |
| FR-4 Versioned History          | 1       |
| FR-5 Rewind                     | 1, 8    |
| FR-6 Steps as Functions         | 1       |
| FR-7 CLI Command Surface        | 8       |
| FR-8 Schema Versioning          | 2, 3    |
| FR-9 Mark-\* Consolidation      | 6       |
| FR-10 Ghost Artifact Removal    | 4       |
| FR-11 Consumer Model Updates    | 2, 7    |
| FR-12 Work Machine Adoption     | 5       |
| NFR-1 No Inference              | 9       |
| NFR-2 Atomic Writes             | 3       |

No orphan requirements. No orphan tasks.

### Scope assessment

9 tasks forming a single coherent behavior change. The "no hybrid intermediate state"
constraint means Tasks 3-7 must be implemented in close succession — splitting would
create coordination cost exceeding session-size benefit. The input is highly detailed
with exact file paths and line numbers ("detail inverts complexity"). Fits one session.

### Grounding verification

All line number references verified against actual code:

- work.py:522,558,773,841 (mark_phase calls) verified
- prepare.py:100-116 (phase routing) verified
- prepare_steps.py: 24 `prepare_phase` write locations verified
- state_io.py:201-237 (read_phase_state) verified
- resource_validation:594 (state.build check) verified
- todo_scaffold.py:207,347 (prepare_phase writes) verified
- prepare_events.py:85-139 (\_derive_prepare_phase) verified
- prepare_events.py:57-66 (\_is_artifact_produced) verified
- prepare_events.py:170 (grounding invalidation write) verified
- api_models.py:213-214,243-244 (TodoDTO build/review fields) verified
- core/models/\_snapshot.py:259-260 (TodoInfo build/review attrs) verified

### Security review

No security concerns — internal state management with no user input at boundaries.

### Policy compliance

- Engine is pure (no I/O) — good separation of concerns
- Migration fallback to `"input_assessment"` is justified (migration default)
- Step functions writing `current` directly is justified in rationale
- Logging cross-cutting section specifies INFO/WARNING levels

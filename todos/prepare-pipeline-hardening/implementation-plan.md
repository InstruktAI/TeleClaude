# Implementation Plan: prepare-pipeline-hardening

## Atomicity verdict

**Atomic.** All 17 requirements interact through shared `DEFAULT_STATE` schema
and prepare step handlers in `core.py`. Splitting into children would create 3-4
todos all touching the same file, same state schema, and same functions — the
coordination cost exceeds the session-size benefit. The requirements are detailed
enough (exact field names, event names, cascade logic, per-step context
specifications) that execution is mechanical.

Estimated change: ~350 lines of new/changed Python across 3-4 files, plus
procedure/spec doc snippet updates.

---

## Task 1: Extend `DEFAULT_STATE` schema with lifecycle and findings fields

**What:** Add new fields to `DEFAULT_STATE` in
`teleclaude/core/next_machine/core.py` (~line 896):

- `artifacts` dict — per-artifact lifecycle metadata:
  ```python
  "artifacts": {
      "input": {"digest": "", "produced_at": "", "consumed_at": "", "stale": False},
      "requirements": {"digest": "", "produced_at": "", "consumed_at": "", "stale": False},
      "implementation_plan": {"digest": "", "produced_at": "", "consumed_at": "", "stale": False},
  }
  ```
- `audit` dict — per-phase timing:
  ```python
  "audit": {
      "input_assessment": {"started_at": "", "completed_at": ""},
      "triangulation": {"started_at": "", "completed_at": ""},
      "requirements_review": {"started_at": "", "completed_at": "", "baseline_commit": "", "verdict": "", "rounds": 0, "findings": []},
      "plan_drafting": {"started_at": "", "completed_at": ""},
      "plan_review": {"started_at": "", "completed_at": "", "baseline_commit": "", "verdict": "", "rounds": 0, "findings": []},
      "gate": {"started_at": "", "completed_at": ""},
  }
  ```
- Structured findings in `requirements_review` and `plan_review`:
  ```python
  "requirements_review": {
      "verdict": "",
      "reviewed_at": "",
      "baseline_commit": "",  # NEW: commit SHA when review dispatched — diff anchor for R17
      "findings_count": 0,
      "rounds": 0,
      "findings": [],  # NEW: list of {id, severity, summary, status, resolved_at}
  }
  ```
  Same pattern for `plan_review`.

- `schema_version` bumped from 1 to 2 at the top level.

**Why:** R5 (lifecycle authority), R7 (audit trail), R1 (finding severity), R9, R17
(schema migration). All downstream tasks depend on these fields existing. The
default-merge in `read_phase_state()` already handles missing keys, so existing
todos get empty defaults transparently — no migration step needed beyond the
version bump.

**Verification:**
- Existing `read_phase_state()` call on a v1 `state.yaml` returns merged state
  with all new fields defaulted.
- Write a unit test: `read_phase_state` on v1 state merges v2 defaults correctly.
- Write a unit test: `read_phase_state` on v2 state preserves all fields.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 896-930)

---

## Task 2: Add artifact lifecycle helper functions

**What:** Add a new module `teleclaude/core/next_machine/prepare_helpers.py` with:

1. `artifact_digest(cwd, slug, artifact_name) -> str` — generic helper. Computes
   SHA-256 of `todos/{slug}/{artifact_name}`. Returns the hex digest, or empty
   string if the file doesn't exist.

2. `record_artifact_digest(cwd, slug, artifact_name)` — calls `artifact_digest`,
   writes the result to `state.yaml.artifacts.<name>.digest`. Emits
   `prepare.artifact_produced` event. Workers call this after producing any
   artifact.

3. `check_artifact_staleness(cwd, slug)` — for each tracked artifact (input,
   requirements, implementation_plan) in cascade order, calls `artifact_digest`
   and compares against the recorded digest in state.yaml. If any differ, returns
   the list of stale artifact names starting from the earliest changed one. All
   downstream artifacts are stale by definition.

4. `record_finding(cwd, slug, review_type, finding)` — appends a structured
   finding `{id, severity, summary, status: "open"}` to the review's `findings`
   list in state.yaml. Emits `prepare.finding_recorded` event.

5. `resolve_finding(cwd, slug, review_type, finding_id, resolution_method)` —
   sets finding `status` to `"resolved"`, records `resolved_at` timestamp. Emits
   `prepare.finding_resolved` event.

6. `stamp_audit(state, phase_name, field, value)` — safely navigates the nested
   `audit` dict and writes a timestamp or value. Used by all phase handlers.

7. `compute_artifact_diff(cwd, slug, artifact_path, base_sha)` — runs
   `git diff {base_sha}..HEAD -- {artifact_path}` via `_run_git_prepare` and
   returns the diff output as a string. Used by step handlers to produce
   `additional_context` for re-dispatched workers (R17). Returns empty string if
   no diff or if base_sha is empty.

8. `compute_todo_folder_diff(cwd, slug, base_sha)` — runs
   `git diff {base_sha}..HEAD -- todos/{slug}/` and returns the diff. Used for
   gate re-dispatch context.

All functions use `read_phase_state` / `write_phase_state` for atomic state
mutations.

**Why:** R8 (generic digest helper for bookkeeping), R17 (worker re-dispatch
context). One helper computes a SHA for any artifact — the same function is used
for recording after production and for checking before routing. Workers call
`record_artifact_digest`. The machine calls `check_artifact_staleness` on every
prepare invocation (Task 3). The diff helpers use the same `_run_git_prepare`
infrastructure already used for codebase grounding. Extracting to a separate
module avoids growing the 4168-line `core.py` further.

**Verification:**
- Unit test: `artifact_digest` returns correct SHA for a known file.
- Unit test: `record_artifact_digest` writes digest to state.yaml.
- Unit test: `check_artifact_staleness` detects mismatch and returns stale list
  in cascade order.
- Unit test: `record_finding` / `resolve_finding` produce correct state mutations.
- Unit test: `compute_artifact_diff` returns git diff output for a changed file.
- Unit test: `compute_artifact_diff` returns empty string when base_sha is empty.
- Unit test: `compute_todo_folder_diff` returns folder-scoped diff.

**Referenced files:**
- `teleclaude/core/next_machine/prepare_helpers.py` (new)
- `teleclaude/core/next_machine/core.py` (imports)

---

## Task 3: Wire staleness check, `additional_context`, and `format_tool_call`

**What:** Three changes wired together in this task:

### 3a. Artifact staleness in the dispatch loop

In `next_prepare()` (~line 3506), after reading state and before the
phase dispatch, call `check_artifact_staleness(cwd, slug)`. If stale artifacts
are returned:

1. Determine the earliest stale artifact in cascade order.
2. Map it to the corresponding phase (input → discovery, requirements → plan
   drafting, implementation_plan → plan review).
3. Set `state["prepare_phase"]` to that phase.
4. Emit `prepare.artifact_invalidated` event with the stale artifact names.
5. Compute the `additional_context` for the re-dispatched worker (see 3c).
6. Write state and continue the dispatch loop — the phase handler takes over.

This check is separate from the existing `_prepare_step_grounding_check`,
which runs at the end of prepare and detects codebase changes (git diff on
referenced paths). Both checks are complementary:
- Artifact staleness (this task): did a todo file change since it was recorded?
  Runs on every prepare call, before routing.
- Codebase grounding (existing): did the source files the plan references
  change between commits? Runs once at the end, after gate passes.

The existing grounding check is not modified.

### 3b. `additional_context` in `format_tool_call`

Add `additional_context: str = ""` parameter to `format_tool_call()` (~line
289). When non-empty, it is included in the dispatch instruction as:

```
ADDITIONAL CONTEXT FOR WORKER:
{additional_context}
```

This appears between the dispatch metadata and the timer step. The orchestrator
passes it to `telec sessions run --additional-context "..."`. Worker commands
receive it as startup frontmatter.

### 3c. Per-step context computation

Each step handler computes `additional_context` for re-dispatch scenarios using
the helpers from Task 2. The machine extracts the most specific diff it can:

| Re-dispatch scenario | Context computed |
|---|---|
| Discovery (input stale) | `compute_artifact_diff(cwd, slug, "todos/{slug}/input.md", base_sha)` |
| Discovery (NEEDS_WORK) | Finding count + pointer + `compute_artifact_diff(cwd, slug, "todos/{slug}/requirements.md", baseline_commit)` |
| Plan draft (requirements stale) | `compute_artifact_diff(cwd, slug, "todos/{slug}/requirements.md", base_sha)` |
| Plan draft (NEEDS_WORK) | Finding count + pointer + `compute_artifact_diff(cwd, slug, "todos/{slug}/implementation-plan.md", baseline_commit)` |
| Plan draft (path existence, R16) | Formatted list of missing paths |
| Scoped re-review | `compute_artifact_diff(cwd, slug, "todos/{slug}/{artifact}", baseline_commit)` + finding IDs |
| Re-grounding | `git diff {base_sha}..HEAD -- {changed_paths}` (existing, enriched) |
| Gate re-dispatch | `compute_todo_folder_diff(cwd, slug, base_sha)` |

First-time dispatches pass `additional_context=""` — no extra context needed.

**Why:** R6 (staleness detection), R17 (worker re-dispatch context). The cascade
runs on every prepare invocation — mechanical SHA comparison, no content
judgment. The per-step context uses the same `_run_git_prepare` infrastructure
already in place for codebase grounding. Workers receive precise scope instead
of generic "redo this phase" instructions.

**Verification:**
- Unit test: modifying `input.md` after recording triggers cascade to
  requirements and plan — phase set to discovery, `additional_context` contains
  the input diff.
- Unit test: modifying `requirements.md` after recording triggers cascade to
  plan only — phase set to plan drafting, `additional_context` contains the
  requirements diff.
- Unit test: no modifications → no staleness, phase routing proceeds normally,
  no `additional_context`.
- Unit test: `format_tool_call` with non-empty `additional_context` includes it
  in output.
- Unit test: `format_tool_call` with empty `additional_context` omits the block.
- Existing grounding check tests continue to pass (not modified).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 289-386, lines 3506-3575)
- `teleclaude/core/next_machine/prepare_helpers.py`

---

## Task 4: Ghost artifact protection in phase derivation

**What:** Update `_derive_prepare_phase()` (~line 2948) to consult
`state.artifacts.<name>.produced_at` alongside file existence. If a file exists on
disk but has no `produced_at` in lifecycle metadata AND the state has
`schema_version >= 2`, the function treats it as not produced.

For v1 states (no `artifacts` metadata), preserve current behavior — file
existence is the only signal. This ensures backward compatibility (R14).

**Why:** R5 (ghost artifact protection). Aborted sessions can leave
`requirements.md` or `implementation-plan.md` on disk without completing the
lifecycle record. The machine must not route based on phantom files.

**Verification:**
- Unit test: v2 state with `requirements.md` on disk but no `produced_at` →
  phase is `INPUT_ASSESSMENT`, not `REQUIREMENTS_REVIEW`.
- Unit test: v1 state with `requirements.md` on disk → phase is
  `REQUIREMENTS_REVIEW` (backward compat).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2948-2977)

---

## Task 5: Review step handlers — structured findings and severity-based verdict

**What:** Update `_prepare_step_requirements_review()` (~line 3044) and
`_prepare_step_plan_review()` (~line 3140):

1. When dispatching a reviewer (first dispatch or re-review), record
   `baseline_commit` = current `HEAD` SHA in the review dict. This is the diff
   anchor for R17 — all subsequent `compute_artifact_diff` calls use it.
2. When reading state, extract the `findings` list from the review dict.
3. Compute unresolved findings: `[f for f in findings if f["status"] == "open"]`.
4. Determine verdict from the highest unresolved severity:
   - No unresolved → APPROVE (auto-remediation closed the loop, R2).
   - Highest is `substantive` → NEEDS_WORK.
   - Highest is `architectural` → NEEDS_DECISION (new verdict value).
5. On NEEDS_WORK dispatch: the note reports the count of unresolved findings
   and points to the findings file. Example: "FIX MODE: 2 unresolved findings.
   See todos/{slug}/requirements-review-findings.md". The worker reads the file
   itself. The machine never reads markdown content to inject into notes.
   Additionally, compute `additional_context` using
   `compute_artifact_diff(cwd, slug, artifact_path, baseline_commit)` — the
   git diff of the artifact since the review baseline recorded in step 1.
   This shows the worker exactly what was written and what the reviewer
   auto-remediated, so the worker can make targeted fixes.
6. On NEEDS_DECISION: set `prepare_phase` to BLOCKED. Output a plain text
   BLOCKED string with the count and pointer: "BLOCKED: {slug} has architectural
   findings requiring human decision. See todos/{slug}/requirements-review-findings.md".
   Emit `prepare.review_scoped` event.
7. Remove the existing pattern (lines 3083-3086, 3178-3181) that reads findings
   markdown files and dumps their content into the note. Replace with the
   count-and-pointer pattern above.
8. On scoped re-review dispatch: record a fresh `baseline_commit` (current
   HEAD), then compute `additional_context` using the artifact diff + unresolved
   finding IDs. The re-reviewer receives the exact changes to verify.

The machine reads structured finding metadata from state.yaml (counts, severity
levels) and routes based on that. It does not read or interpret finding content
from markdown files. Severity classification is the reviewer's job (R1).

**Why:** R1 (finding severity), R2 (auto-remediation closes loop), R3 (scoped
re-reviews), R17 (worker re-dispatch context). This is the core efficiency
improvement: a reviewer that fixes all trivial findings inline produces
unresolved=0 → APPROVE → no fix worker → no re-review. Re-dispatched workers
receive the artifact diff as `additional_context` so they can make targeted
fixes. The output stays generic — counts, file pointers, and diffs — not
content interpretation.

**Verification:**
- Unit test: all findings resolved → verdict APPROVE, no fix dispatch.
- Unit test: substantive unresolved → NEEDS_WORK, note contains count and file
  pointer, `additional_context` contains artifact diff since review baseline.
- Unit test: architectural unresolved → NEEDS_DECISION, phase set to BLOCKED.
- Unit test: scoped re-review includes artifact diff + finding IDs in
  `additional_context`.
- Unit test: no markdown file content appears in any machine output.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 3044-3108, lines 3140-3203)

---

## Task 6: Audit trail stamping in phase handlers

**What:** In each prepare step handler, call `stamp_audit(state, phase, "started_at",
now)` when entering the phase and `stamp_audit(state, phase, "completed_at", now)`
when transitioning out. For review phases, also record verdict and rounds.

**Why:** R7 (per-phase audit trail). Observability bookkeeping for debugging and
analytics. The audit trail is additional to — not a replacement for — the
`prepare_phase` routing field.

**Verification:**
- Unit test: after a full prepare cycle mock, all audit phases have `started_at`
  and `completed_at` populated.
- Unit test: review audit phases have `verdict` and `rounds`.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (all `_prepare_step_*` functions)
- `teleclaude/core/next_machine/prepare_helpers.py` (`stamp_audit`)

---

## Task 7: Split inheritance — children inherit parent phase

**What:** Update `split_todo()` in `teleclaude/todo_scaffold.py` (~line 157):

1. Read parent state before splitting.
2. Determine parent's highest approved phase:
   - `requirements_review.verdict == "approve"` → approved through requirements.
   - `plan_review.verdict == "approve"` → approved through plan.
3. For each child:
   - Copy the relevant parent artifacts (requirements.md if approved,
     implementation-plan.md if plan approved).
   - Set child `state.yaml` fields:
     - Copy parent's review verdicts for approved phases.
     - Set `prepare_phase` to the next phase after the inherited approval.
     - For skipped phases, write `audit.<phase>` entries with
       `status: "skipped"`, `reason: "inherited_from_parent"`,
       `skipped_at: <timestamp>`.
   - Copy parent's `artifacts` lifecycle metadata for inherited artifacts.
4. Emit `prepare.split_inherited` event per child with parent slug, child slug,
   and inherited phase.
5. Emit `prepare.phase_skipped` event for each skipped phase per child.

**Why:** R10 (split inherits parent state), R11 (phase skip observability). This
prevents the 8x ceremony problem: children of an approved parent start at the
next phase, not at discovery.

**Verification:**
- Unit test: parent with approved requirements → children have
  `prepare_phase=plan_drafting`, requirements_review verdict=approve,
  requirements.md copied.
- Unit test: parent with approved plan → children have
  `prepare_phase=gate`, both review verdicts copied, all artifacts copied.
- Unit test: parent with only input.md → children start at discovery (current
  behavior preserved).
- Unit test: skipped phases have `status: "skipped"` audit entries.

**Referenced files:**
- `teleclaude/todo_scaffold.py` (lines 157-250)

---

## Task 8: Register new events in event vocabulary

**What:** Add 8 new event registrations in
`teleclaude/events/schemas/software_development.py` under the "Prepare lifecycle
events" section (~line 194):

1. `domain.software-development.prepare.phase_skipped` — phase skipped by
   inheritance, carries phase name and reason.
2. `domain.software-development.prepare.input_consumed` — input consumed by
   discovery, carries phase and digest.
3. `domain.software-development.prepare.artifact_produced` — artifact written
   and lifecycle-tracked, carries artifact name and digest.
4. `domain.software-development.prepare.artifact_invalidated` — upstream change
   cascaded staleness, carries artifact name and reason.
5. `domain.software-development.prepare.finding_recorded` — finding recorded by
   reviewer, carries severity and summary.
6. `domain.software-development.prepare.finding_resolved` — finding resolved,
   carries resolution method.
7. `domain.software-development.prepare.review_scoped` — scoped re-review
   dispatched, carries finding IDs.
8. `domain.software-development.prepare.split_inherited` — child inherited
   parent state, carries parent slug, child slug, inherited phase.

Follow the existing `EventSchema` pattern with appropriate `EventLevel`,
`idempotency_fields`, and `NotificationLifecycle` settings.

Also enrich existing events:
- `prepare.requirements_approved` and `prepare.plan_approved` — add finding
  summary (count by severity) to their payloads in the step handlers.

**Why:** R13 (event coverage). Events make every state transition observable
without polling state.yaml.

**Verification:**
- Unit test: `register_all()` includes all new event types without errors.
- Verify event type strings match the constants used in `_emit_prepare_event`
  calls.

**Referenced files:**
- `teleclaude/events/schemas/software_development.py` (lines 194-301)
- `teleclaude/core/next_machine/core.py` (event emission calls)
- `teleclaude/core/next_machine/prepare_helpers.py` (event emission calls)

---

## Task 9: Update procedure and spec doc snippets

**What:** Update the following doc snippets to reflect the new behaviors:

1. `docs/global/software-development/procedure/lifecycle/review-requirements.md` — add
   finding severity classification guidance (trivial/substantive/architectural),
   auto-remediation boundary (R4: factual corrections vs scope expansions), and
   the rule that all-resolved → APPROVE.

2. `docs/global/software-development/procedure/lifecycle/review-plan.md` — same
   severity and auto-remediation guidance for plan reviews.

3. `docs/global/software-development/procedure/maintenance/next-prepare-discovery.md` —
   add R12 (independent verification of measurable claims before writing
   requirements).

4. `docs/global/software-development/procedure/lifecycle/prepare.md` — update overview
   to mention artifact lifecycle tracking, staleness cascade, and split
   inheritance.

5. `docs/project/spec/event-vocabulary.md` — add the 8 new prepare events to
   the event families table and document their payload fields.

**Why:** R15 (documentation updates). All affected procedures, specs, and
policies must reflect the new behaviors. The builder resolves doc snippet paths
at build time via `telec docs index`.

**Verification:**
- Each updated snippet passes `telec sync --validate-only`.
- Cross-reference: every new behavior in Tasks 1-8 has a corresponding
  documentation mention.

**Referenced files:**
- `docs/global/software-development/procedure/lifecycle/review-requirements.md`
- `docs/global/software-development/procedure/lifecycle/review-plan.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-discovery.md`
- `docs/global/software-development/procedure/lifecycle/prepare.md`
- `docs/project/spec/event-vocabulary.md`

---

## Task 10: Integration tests for schema migration and cross-cutting behavior

**What:** Add tests in `tests/unit/` verifying:

1. **Schema migration**: a v1 `state.yaml` (no `artifacts`, no `audit`, no
   `findings` in reviews) read through `read_phase_state()` returns a complete v2
   state with all defaults populated.

2. **Ghost artifact protection**: file exists on disk + v2 state with no
   `produced_at` → phase derivation skips the file.

3. **Backward compat**: file exists on disk + v1 state → phase derivation
   respects the file (current behavior).

4. **Split inheritance**: end-to-end test through `split_todo()` with a parent
   at various approval stages.

5. **Staleness cascade**: modify input after consumption → requirements and plan
   stale. Modify requirements after consumption → only plan stale.

6. **Review efficiency**: findings with mixed severities → correct verdict and
   dispatch behavior.

These tests use the existing test infrastructure — `tmp_path` for todo
directories, mock state files, no daemon required.

**Why:** R9 (schema migration), R14 (backward compatibility). These are the
cross-cutting correctness checks that span multiple tasks.

**Verification:**
- All tests pass in `make test-unit`.
- Pre-commit hooks pass.

**Referenced files:**
- `tests/unit/test_prepare_helpers.py` (new)
- `tests/unit/test_prepare_schema_migration.py` (new or extend existing)
- `tests/unit/test_split_inheritance.py` (new)

---

## Task 11: Referenced path existence check after plan drafting

**What:** In the prepare dispatch loop (`next_prepare()` in `core.py`), after
the plan drafting phase completes and before advancing to plan review: read
`state.grounding.referenced_paths` and check each path exists on disk relative
to the project root. If any paths do not exist, return a re-draft instruction
instead of advancing to plan review.

The list of missing paths is passed as `additional_context` in the re-draft
dispatch. The drafter receives exactly which paths failed to resolve and can
correct them without re-reading the entire plan.

**Why:** R16 (referenced path existence check), R17 (worker re-dispatch
context). The drafter produced file paths in this very todo that didn't exist —
`docs/software-development/...` instead of `docs/global/software-development/...`.
This is a mechanical fact check: does the file resolve? The machine already
reads `referenced_paths` for staleness detection; adding an existence check is
one conditional in the same code path. The missing paths flow as structured
`additional_context`, not as prose in the note.

**Verification:**
- Unit test: plan with non-existent `referenced_paths` → machine returns
  re-draft instruction with missing paths in `additional_context`.
- Unit test: plan with all valid `referenced_paths` → machine advances to
  plan review normally, no `additional_context`.
- Unit test: plan with empty `referenced_paths` → machine advances (no paths
  to validate).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 3506-3575, plan drafting
  completion transition)

---

## Dependency order

Tasks 1 → 2 → 3 (schema → helpers → wiring + format_tool_call + per-step
context). Task 4 depends on Task 1. Tasks 5-6 depend on Tasks 1-3 (review
handlers use diff helpers and `additional_context` from Task 3). Task 7 depends
on Tasks 1-2. Task 8 can proceed in parallel with Tasks 4-7. Task 9 depends on
Tasks 1-8 (documents what was built). Task 10 is written test-first per TDD
policy — the tests for each task are written as part of that task, but Task 10
covers the cross-cutting integration tests that span multiple tasks. Task 11
depends on Task 3 (wired into the same dispatch loop, uses `additional_context`).

Recommended build order: 1 → 2 → 3 → [4, 5, 6, 7, 8, 11 in parallel where
possible] → 9 → 10 (integration tests).

Per TDD policy, each task starts with a failing test before writing production
code. Task 10 is the integration test sweep at the end.

---

## Requirements traceability

| Requirement | Task(s) | Verification |
|---|---|---|
| R1 (finding severity) | 1, 2, 5 | Unit test: severity-based verdict routing |
| R2 (auto-remediation closes loop) | 5 | Unit test: unresolved=0 → APPROVE |
| R3 (scoped re-reviews) | 5 | Unit test: instruction includes only unresolved findings |
| R4 (auto-remediation boundary) | 9 | Procedure doc update |
| R5 (lifecycle authority) | 1, 2, 4 | Unit test: ghost artifact protection |
| R6 (staleness cascade) | 2, 3 | Unit test: digest-based cascade |
| R7 (audit trail) | 1, 6 | Unit test: timestamps populated after cycle |
| R8 (helper functions) | 2 | Unit test: helpers produce correct state |
| R9 (schema migration) | 1, 10 | Unit test: v1 → v2 merge |
| R10 (split inheritance) | 7 | Unit test: children inherit phase |
| R11 (phase skip observability) | 7 | Unit test: skipped audit entries |
| R12 (verification hardening) | 9 | Procedure doc update |
| R13 (event coverage) | 8 | Unit test: all events registered |
| R14 (backward compat) | 1, 4, 10 | Unit test: v1 state behavior preserved |
| R15 (documentation) | 9 | Snippet validation |
| R16 (path existence check) | 11 | Unit test: missing paths → re-draft instruction |
| R17 (worker re-dispatch context) | 2, 3, 5, 11 | Unit test: per-step additional_context computed and passed |

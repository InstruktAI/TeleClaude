# Implementation Plan: prepare-pipeline-hardening

## Atomicity verdict

**Atomic.** All 17 requirements interact through shared `DEFAULT_STATE` schema
and prepare step handlers in `core.py`. Splitting into children would create 3-4
todos all touching the same file, same state schema, and same functions — the
coordination cost exceeds the session-size benefit. The requirements are detailed
enough (exact field names, event names, cascade logic, per-step context
specifications) that execution is mechanical.

Estimated change: ~400 lines of new/changed Python across 5-6 files, plus
procedure/spec doc snippet updates.

---

## Task 1: Extend `DEFAULT_STATE` schema with lifecycle and findings fields

**What:** Add new fields to `DEFAULT_STATE` in
`teleclaude/core/next_machine/core.py` (~line 912):

- `artifacts` dict — per-artifact lifecycle metadata (no `consumed_at` — digest
  comparison is sufficient for staleness; consumption tracking adds dead schema):
  ```python
  "artifacts": {
      "input": {"digest": "", "produced_at": "", "stale": False},
      "requirements": {"digest": "", "produced_at": "", "stale": False},
      "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
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
(schema migration). All downstream tasks depend on these fields existing.

The existing `read_phase_state()` uses a shallow `merged.update(state)` at line
~980. This is insufficient for nested dicts: a v1 `requirements_review: {verdict:
"approve", findings_count: 2, rounds: 1}` completely replaces the DEFAULT_STATE
counterpart, losing the new `baseline_commit` and `findings` sub-keys. Task 1 must
also implement a deep-merge for nested state dicts.

Add a private helper `_deep_merge_state(defaults: dict, persisted: dict) -> dict`
adjacent to `read_phase_state` that recursively merges nested dicts instead of
overwriting them. Apply it to these nested keys: `requirements_review`,
`plan_review`, `grounding`, `artifacts`, `audit`. Use it in `read_phase_state`
instead of `merged.update(state)` for those keys.

**Verification:**
- Unit test (TDD first): `read_phase_state` on a v1 `state.yaml` returns merged
  state with all v2 nested sub-keys defaulted (e.g., `requirements_review.findings`,
  `requirements_review.baseline_commit`, `artifacts.input.produced_at`).
- Unit test: `read_phase_state` on a v2 state with partially populated nested dicts
  preserves all non-default sub-keys.
- Unit test: `read_phase_state` on v2 state preserves all fields unchanged.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 912-950, 960-985)

---

## Task 2: Add artifact lifecycle helper functions

**What:** Add a new module `teleclaude/core/next_machine/prepare_helpers.py` with:

1. `artifact_digest(cwd, slug, artifact_name) -> str` — generic helper. Computes
   SHA-256 of `todos/{slug}/{artifact_name}`. Returns the hex digest, or empty
   string if the file doesn't exist.

2. `record_artifact_produced(cwd, slug, artifact_name)` — calls `artifact_digest`,
   writes the result to `state.yaml.artifacts.<name>.digest`, and also writes
   `state.yaml.artifacts.<name>.produced_at` with a UTC timestamp. Emits
   `prepare.artifact_produced` event. Workers call this after producing any
   artifact. Both `digest` and `produced_at` are written atomically in one
   `write_phase_state` call.

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

9. `record_input_consumed(cwd, slug)` — computes the current SHA of
   `todos/{slug}/input.md` and emits `prepare.input_consumed` event with
   `{"phase": "input_assessment", "digest": <sha>}`. Called by
   `_prepare_step_input_assessment` immediately before transitioning to
   `requirements_review` when requirements.md is found to be produced. Does not
   modify state.yaml — it is a pure observation event.

All functions use `read_phase_state` / `write_phase_state` for atomic state
mutations.

**Why:** R8 (generic digest helper for bookkeeping), R17 (worker re-dispatch
context). `record_artifact_produced` is the single write point — one function,
one call, writes both `digest` and `produced_at`. This makes ghost artifact
protection (Task 4) unambiguous: if `produced_at` is empty, the artifact was
never properly recorded. The diff helpers use the same `_run_git_prepare`
infrastructure already used for codebase grounding. Extracting to a separate
module avoids growing the 4168-line `core.py` further.

**Verification:**
- Unit test: `artifact_digest` returns correct SHA for a known file.
- Unit test: `record_artifact_produced` writes both `digest` and `produced_at`
  to state.yaml in one call.
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

In `next_prepare()` (~line 3525), after reading state and before the
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

Add `additional_context: str = ""` parameter to `format_tool_call()` (~line 285).
When non-empty, it is included in the dispatch instruction as:

```
ADDITIONAL CONTEXT FOR WORKER:
{additional_context}
```

This appears between the dispatch metadata and the timer step. The rendered
`telec sessions run` call in the output includes `--additional-context
"{additional_context}"` when non-empty. The `--additional-context` CLI flag is
implemented in Task 12.

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

Additionally, in `_prepare_step_input_assessment`: when requirements.md is found
to be produced (i.e., `artifacts.requirements.produced_at` is non-empty, or for
v1 states, `requirements.md` exists), call `record_input_consumed(cwd, slug)`
immediately before transitioning to `requirements_review`. This is the single
emission point for `prepare.input_consumed` (R13). The step handler already
handles this transition — this adds one helper call at that junction.

**Why:** R6 (staleness detection), R17 (worker re-dispatch context), R13 (input_consumed event). The cascade
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
  in output and includes `--additional-context` in rendered `telec sessions run`.
- Unit test: `format_tool_call` with empty `additional_context` omits the block.
- Unit test: `_prepare_step_input_assessment` emits `prepare.input_consumed` when
  transitioning to requirements_review (requirements found produced).
- Existing grounding check tests continue to pass (not modified).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 285-386, lines 3004-3031, lines 3525-3595)
- `teleclaude/core/next_machine/prepare_helpers.py`

---

## Task 4: Ghost artifact protection in phase derivation

**What:** Update `_derive_prepare_phase()` (~line 2967) to consult
`state.artifacts.<name>.produced_at` alongside file existence. If a file exists on
disk but has no `produced_at` in lifecycle metadata AND the state has
`schema_version >= 2`, the function treats it as not produced.

For v1 states (no `artifacts` metadata), preserve current behavior — file
existence is the only signal. This ensures backward compatibility (R14).

**Why:** R5 (ghost artifact protection). Aborted sessions can leave
`requirements.md` or `implementation-plan.md` on disk without completing the
lifecycle record. The machine must not route based on phantom files.

**Verification:**
- Unit test (TDD first): v2 state with `requirements.md` on disk but no
  `produced_at` → phase is `INPUT_ASSESSMENT`, not `REQUIREMENTS_REVIEW`.
- Unit test: v1 state with `requirements.md` on disk → phase is
  `REQUIREMENTS_REVIEW` (backward compat).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2967-2996)

---

## Task 5: Review step handlers — structured findings and severity-based verdict

**What:** Update `_prepare_step_requirements_review()` (~line 3063) and
`_prepare_step_plan_review()` (~line 3159):

1. When dispatching a reviewer (first dispatch or re-review), record
   `baseline_commit` = current `HEAD` SHA in the review dict. This is the diff
   anchor for R17 — all subsequent `compute_artifact_diff` calls use it.
2. When reading state, extract the `findings` list from the review dict using
   `.get("findings", [])` — safe for both v1 states (no `findings` key) and v2.
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

9. **Add `needs_decision` to `_PREPARE_VERDICT_VALUES`** at line 1069:
   ```python
   _PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")
   ```
   `teleclaude/api/todo_routes.py` imports `_PREPARE_VERDICT_VALUES` from
   `core.py` (line 33) and uses it at line 142 for API validation — adding
   the value here transitively fixes the API endpoint. No change needed in
   `todo_routes.py`.
10. Update the `telec todo mark-phase` help text in `teleclaude/cli/telec.py`
    so the `--status` description includes `needs_decision` alongside the
    existing prepare verdicts. The accepted surface changed, so the help output
    must change with it.

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
- Unit test: v1 state without `findings` key does not raise KeyError.
- Unit test: `_PREPARE_VERDICT_VALUES` includes `needs_decision` — passing
  `needs_decision` to `mark_prepare_verdict` does not raise `ValueError`.
- Unit test: the `/todos/mark-phase` API endpoint accepts `needs_decision` verdict
  without 422 error (validates via `_PREPARE_VERDICT_VALUES`).
- Verify `telec todo mark-phase --help` (or the `CommandDef` surface in
  `teleclaude/cli/telec.py`) documents `needs_decision` as an allowed prepare
  verdict.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 1069, 3063-3127, lines 3159-3222)
- `teleclaude/cli/telec.py`

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

**What:** Update `split_todo()` in `teleclaude/todo_scaffold.py` (~line 159):

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
6. Update the `telec todo split` help text in `teleclaude/cli/telec.py` so the
   command description/notes explain that children inherit approved parent
   state instead of always restarting from discovery.

**Why:** R10 (split inherits parent state), R11 (phase skip observability). This
prevents the 8x ceremony problem: children of an approved parent start at the
next phase, not at discovery.

**Verification:**
- Unit test: parent with approved requirements → children have
  `prepare_phase=plan_drafting`, requirements_review verdict=approve,
  requirements.md copied.
- Unit test: parent with approved plan → children have
  `prepare_phase=prepared`, both review verdicts copied, all artifacts copied.
  (`PREPARED = "prepared"` is the phase indicating prepare is complete and the
  todo is ready for build — the gate was already passed by the parent.)
- Unit test: parent with only input.md → children start at discovery (current
  behavior preserved).
- Unit test: skipped phases have `status: "skipped"` audit entries.
- Verify `telec todo split --help` reflects the inherited-approval behavior.

**Referenced files:**
- `teleclaude/todo_scaffold.py` (lines 159-260)
- `teleclaude/cli/telec.py`

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

6. `docs/project/spec/telec-cli-surface.md` — add `--additional-context` to the
   `sessions run` command description and flag list. Also update the `todo split`
   command description to reflect that children inherit parent approval state.

7. `docs/global/software-development/procedure/maintenance/next-prepare-draft.md` —
   add note that re-dispatched draft workers receive `additional_context` in their
   startup frontmatter containing the requirements diff or missing path list.

8. `docs/global/software-development/procedure/maintenance/next-prepare-gate.md` —
   add note that gate re-dispatch includes `additional_context` with the full todo
   folder diff.

9. `docs/global/software-development/procedure/maintenance/next-prepare.md` —
   update the lifecycle state machine overview to reflect: artifact staleness
   cascade, split inheritance (children skip phases already approved by parent),
   `BLOCKED` phase for `NEEDS_DECISION` architectural findings, and
   `record_input_consumed` emission at the input_assessment → requirements_review
   transition.

**Why:** R15 (documentation updates). All affected procedures, specs, and
policies must reflect the new behaviors. The builder resolves doc snippet paths
at build time via `telec docs index`.

**Verification:**
- Each updated snippet passes `telec sync --validate-only`.
- Cross-reference: every new behavior in Tasks 1-8, 11-13 has a corresponding
  documentation mention.

**Referenced files:**
- `docs/global/software-development/procedure/lifecycle/review-requirements.md`
- `docs/global/software-development/procedure/lifecycle/review-plan.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-discovery.md`
- `docs/global/software-development/procedure/lifecycle/prepare.md`
- `docs/project/spec/event-vocabulary.md`
- `docs/project/spec/telec-cli-surface.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-draft.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-gate.md`
- `docs/global/software-development/procedure/maintenance/next-prepare.md`

---

## Task 10: Integration tests for schema migration and cross-cutting behavior

**What:** Add tests in `tests/unit/` verifying:

1. **Schema migration**: a v1 `state.yaml` (no `artifacts`, no `audit`, no
   `findings` in reviews) read through `read_phase_state()` returns a complete v2
   state with all defaults populated — including nested sub-keys like
   `requirements_review.findings` and `artifacts.input.produced_at`.

2. **Ghost artifact protection**: file exists on disk + v2 state with no
   `produced_at` → phase derivation skips the file.

3. **Backward compat**: file exists on disk + v1 state → phase derivation
   respects the file (current behavior).

4. **Split inheritance**: end-to-end test through `split_todo()` with a parent
   at various approval stages.

5. **Staleness cascade**: modify input after production → requirements and plan
   stale. Modify requirements after production → only plan stale.

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
- `teleclaude/core/next_machine/core.py` (lines 3525-3595, plan drafting
  completion transition)

---

## Task 12: Implement `--additional-context` CLI flag for `telec sessions run`

**What:** Thread `additional_context` through the session launch stack:

1. **`teleclaude/api_models.py`** (~line 582): add `additional_context: str = ""`
   to `RunSessionRequest`. This is the API boundary field.

2. **`teleclaude/api_server.py`** (~line 1406): in `run_session`, after building
   `full_command`, append `additional_context` when non-empty:
   ```python
   if request.additional_context:
       full_command = f"{full_command}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"
   ```
   This injects the context into the startup message the worker receives verbatim.
   Quote the combined string before passing to `auto_command`.

3. **`teleclaude/cli/tool_commands.py`** (~line 372): in `handle_sessions_run`,
   add `--additional-context` to the arg-parsing loop:
   ```python
   elif args[i] == "--additional-context" and i + 1 < len(args):
       body["additional_context"] = args[i + 1]
       i += 2
   ```

4. **`teleclaude/cli/telec.py`** (~line 257): add the flag to the `sessions run`
   `CommandDef`:
   ```python
   Flag("--additional-context", desc="Additional context for the worker, appended to startup message"),
   ```

5. **`teleclaude/core/next_machine/core.py`** (`format_tool_call`, ~line 285):
   add `additional_context: str = ""` parameter. When non-empty, render it in the
   `telec sessions run` call:
   ```
   telec sessions run --command "..." --args "..." ... --additional-context "{additional_context}"
   ```
   and include the `ADDITIONAL CONTEXT FOR WORKER:` block in the output text
   between dispatch metadata and the timer step.

**Why:** R17 (worker re-dispatch context). Without this flag, the `additional_context`
computed by the step handlers (Task 3) has no delivery channel. The flag
closes the loop: `format_tool_call` renders it → orchestrator reads the
dispatch instruction and passes `--additional-context` → `telec sessions run`
appends it to the startup message → the worker reads it as part of the command
frontmatter. The full chain is the existing session launch path plus one new
field at each layer.

**Verification:**
- Unit test: `RunSessionRequest` with non-empty `additional_context` → appended
  to the startup message sent to the worker.
- Unit test: `RunSessionRequest` with empty `additional_context` → startup
  message unchanged (no "ADDITIONAL CONTEXT:" block).
- Unit test: `format_tool_call` with non-empty `additional_context` includes
  `--additional-context` in rendered `telec sessions run` command.
- Unit test: `format_tool_call` with empty `additional_context` omits the flag.

**Referenced files:**
- `teleclaude/api_models.py` (line 582)
- `teleclaude/api_server.py` (line ~1406)
- `teleclaude/cli/tool_commands.py` (line ~372)
- `teleclaude/cli/telec.py` (line ~257)
- `teleclaude/core/next_machine/core.py` (line 285)

---

---

## Task 13: Update `demo.md` for user-visible CLI and dispatch changes

**What:** Update `todos/prepare-pipeline-hardening/demo.md` to add validation
sections for the three user-visible behaviors introduced by this todo:

1. **BLOCKED output**: Show that an architectural finding in state.yaml produces
   the BLOCKED string output from `next_prepare()` with count and file pointer.
   ```bash
   # Simulate architectural finding in state, run next_prepare,
   # verify output contains "BLOCKED:" and the findings file pointer.
   ```

2. **`--additional-context` CLI flag**: Show that `telec sessions run
   --additional-context "..."` is accepted and that the worker's startup message
   includes the context block. Demonstrate via the `RunSessionRequest` model.

3. **`prepare.input_consumed` event emission**: Show the event fires when
   `_prepare_step_input_assessment` transitions to requirements_review. The
   event carries `phase` and `digest` payload fields.

Also add a "Step 7: BLOCKED escalation path" to the Guided Presentation
section describing how an architectural finding surfaces to the orchestrator.

**Why:** R13 (event coverage — demo now shows input_consumed emission), R17
(demo shows `--additional-context` flag end-to-end), R1 (demo shows BLOCKED
output for architectural findings). The plan reviewer cited missing demo
coverage for Tasks 3, 5, 11, and 12 as an I-class finding — completing `demo.md`
satisfies the review-plan DoD gate requirement for demo coverage of user-facing
changes.

**Verification:**
- `telec todo demo validate prepare-pipeline-hardening` passes.
- Demo sections for BLOCKED output, `--additional-context`, and
  `prepare.input_consumed` are all present and runnable.

**Referenced files:**
- `todos/prepare-pipeline-hardening/demo.md`

---

## Dependency order

Tasks 1 → 2 → 3 (schema → helpers → wiring + format_tool_call + per-step
context). Task 3 also depends on Task 12 (format_tool_call renders the
`--additional-context` flag that Task 12 adds to the CLI). Task 4 depends on
Task 1. Tasks 5-6 depend on Tasks 1-3 (review handlers use diff helpers and
`additional_context` from Task 3). Task 7 depends on Tasks 1-2. Task 8 can
proceed in parallel with Tasks 4-7. Task 9 depends on Tasks 1-8 (documents
what was built). Task 10 is written test-first per TDD policy — the tests for
each task are written as part of that task, but Task 10 covers the
cross-cutting integration tests that span multiple tasks. Task 11 depends on
Task 3 (wired into the same dispatch loop, uses `additional_context`). Task 12
can be developed in parallel with Tasks 1-2 since it touches different files.
Task 13 depends on Tasks 5, 12 (demo covers what they built).

Recommended build order: [1, 12 in parallel] → 2 → 3 → [4, 5, 6, 7, 8, 11 in
parallel where possible] → 9 → 10 (integration tests) → 13 (demo).

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
| R9 (schema migration) | 1, 10 | Unit test: v1 → v2 deep merge |
| R10 (split inheritance) | 7 | Unit test: children inherit phase |
| R11 (phase skip observability) | 7 | Unit test: skipped audit entries |
| R12 (verification hardening) | 9 | Procedure doc update |
| R13 (event coverage) | 2, 3, 8 | Unit test: all events registered; input_consumed emitted at transition |
| R14 (backward compat) | 1, 4, 10 | Unit test: v1 state behavior preserved |
| R15 (documentation) | 9 | Snippet validation |
| R16 (path existence check) | 11 | Unit test: missing paths → re-draft instruction |
| R17 (worker re-dispatch context) | 2, 3, 5, 11, 12, 13 | Unit test: per-step additional_context computed and passed; demo validates |

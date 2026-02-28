# Implementation Plan: Prepare Quality Runner

## Overview

Deliver an event-driven notification handler that reacts to todo lifecycle events,
assesses DOR quality, improves artifacts when safe, and resolves the triggering
notification with the assessment result.

The handler integrates with the notification service as a registered consumer.
It uses the existing `next-prepare-draft` and `next-prepare-gate` procedures as
the assessment model, but runs as an automated handler rather than a manual invocation.

## Phase 1: Handler Registration & Event Wiring

### Task 1.1: Register handler with notification service

**File(s):** `teleclaude/services/prepare_quality_handler.py` (new)

- [ ] Create handler module with `PrepareQualityHandler` class
- [ ] Register interest in event types: `todo.artifact_changed`, `todo.created`,
      `todo.dumped`, `todo.activated`, `todo.dependency_resolved`
- [ ] Implement `async handle(notification_id: int, envelope: EventEnvelope)` entry point
- [ ] Handler claims the notification via API before starting work
- [ ] On error: release claim, log, do not resolve

**Verification:** Handler is called when a todo lifecycle event is emitted.

### Task 1.2: Event filtering and idempotency

**File(s):** `teleclaude/services/prepare_quality_handler.py`

- [ ] Extract slug from event payload
- [ ] Skip if slug is in `todos/delivered.yaml` or `todos/icebox.md`
- [ ] Compute current commit hash of `todos/{slug}/` folder
- [ ] Compare with `state.yaml` dor `assessed_commit`:
  - Same commit + `status == pass` → resolve notification as no-op, return
  - Different commit or no prior assessment → proceed
- [ ] Log skip reason when idempotency triggers

**Verification:** Duplicate event for unchanged slug is skipped. Changed slug is processed.

## Phase 2: DOR Assessment Engine

### Task 2.1: Artifact quality scorer

**File(s):** `teleclaude/services/dor_scorer.py` (new)

- [ ] Define scoring rubric as structured criteria:
  - Requirements: intent clarity (0-2), scope atomicity (0-2), testable success criteria (0-2),
    dependency correctness (0-1), constraint specificity (0-1), verification path (0-2)
  - Plan: concrete file targets (0-2), verification steps (0-2), risk identification (0-1),
    task-to-requirement traceability (0-2), plan-requirement consistency (0-3)
- [ ] `async score_requirements(content: str, slug: str) -> ScoringResult`
- [ ] `async score_plan(content: str, requirements: str, slug: str) -> ScoringResult`
- [ ] `ScoringResult` dataclass: `score` (int 1..10), `gaps` (list[str]),
      `improvements_possible` (list[str]), `blockers` (list[str])
- [ ] Combine into overall DOR score with verdict derivation:
  - > = 8 → `pass`
  - < 8 with improvements possible → `needs_work`
  - < 7 with no safe improvements → `needs_decision`

**Verification:** Unit tests for scoring thresholds and verdict mapping across fixture todos.

### Task 2.2: Plan-requirement consistency checker

**File(s):** `teleclaude/services/dor_scorer.py`

- [ ] Check every plan task traces to at least one requirement
- [ ] Check no plan task contradicts a requirement
- [ ] Flag contradictions as blockers (e.g., plan says "copy" when requirement says "reuse")
- [ ] Contradiction between plan and requirements is a `needs_work` blocker

**Verification:** Fixture with contradicting plan/requirement produces `needs_work` with
specific contradiction listed.

## Phase 3: Safe Improvement

### Task 3.1: Artifact improver

**File(s):** `teleclaude/services/prepare_quality_improver.py` (new)

- [ ] `async improve_artifacts(slug: str, scoring: ScoringResult) -> ImprovementResult`
- [ ] When `requirements.md` is missing: generate from `input.md` + codebase context
- [ ] When `implementation-plan.md` is missing: generate from requirements + codebase
- [ ] When artifacts exist but weak: tighten specific sections identified by scorer
- [ ] Uncertainty boundary: stop and record blockers when grounding is insufficient
- [ ] Return `ImprovementResult`: `edits_made` (list[str]), `artifacts_updated` (list[str]),
      `remaining_gaps` (list[str])

**Verification:** Fixture with missing plan gets generated plan. Ambiguous fixture
remains blocked with explicit rationale.

### Task 3.2: Post-improvement reassessment

**File(s):** `teleclaude/services/prepare_quality_handler.py`

- [ ] After improvement, re-run scorer on updated artifacts
- [ ] Update score and verdict based on improved state
- [ ] If still below threshold after improvement: verdict is final

**Verification:** Improved artifact rescores higher. Still-weak artifact stays at lower score.

## Phase 4: Output & Resolution

### Task 4.1: DOR report writer

**File(s):** `teleclaude/services/dor_report_writer.py` (new)

- [ ] Write `todos/{slug}/dor-report.md` with fixed template:
  - Score + verdict
  - Assessment timestamp
  - Edits performed (if any)
  - Remaining gaps
  - Blockers / decisions needed
- [ ] Deterministic output format for machine and human readability

**Verification:** Report content matches scoring result for fixture todos.

### Task 4.2: State writeback

**File(s):** `teleclaude/services/prepare_quality_handler.py`

- [ ] Read existing `state.yaml` and update dor section:
  - `last_assessed_at`, `score`, `status`, `schema_version`, `blockers`,
    `actions_taken`, `assessed_commit`
- [ ] Preserve all non-dor keys in `state.yaml`
- [ ] Use YAML safe dump with consistent formatting

**Verification:** state.yaml dor section matches schema. Non-dor keys preserved.

### Task 4.3: Notification resolution

**File(s):** `teleclaude/services/prepare_quality_handler.py`

- [ ] On `pass` or `needs_work`: resolve notification via API with structured result
  - `summary`: "DOR {status} ({score}/10) for {slug}"
  - `resolved_by`: "prepare-quality-runner"
  - `resolved_at`: current timestamp
- [ ] On `needs_decision`: do NOT resolve — leave notification unresolved
- [ ] Emit `todo.dor_assessed` event with score and verdict for downstream consumers

**Verification:** Notification API shows resolved notification for pass/needs_work.
Unresolved notification remains visible for needs_decision.

## Phase 5: Daemon Integration

### Task 5.1: Wire handler into daemon startup

**File(s):** `teleclaude/daemon.py`

- [ ] Import and instantiate `PrepareQualityHandler`
- [ ] Register handler with notification processor for todo lifecycle events
- [ ] Handler lifecycle follows daemon lifecycle (start/stop)

**Verification:** Daemon startup logs show handler registered. Event emission triggers handler.

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Unit tests for DOR scorer (rubric evaluation, threshold mapping)
- [ ] Unit tests for idempotency (skip logic, commit hash comparison)
- [ ] Unit tests for artifact improver (generation, tightening, uncertainty boundary)
- [ ] Integration test: emit event → handler claims → assesses → resolves notification
- [ ] Test `needs_decision` path: notification left unresolved
- [ ] Run `make test`

### Task 6.2: Quality checks

- [ ] Run `make lint`
- [ ] Verify handler does not import `teleclaude_notifications.*` internals
- [ ] Verify state.yaml schema compliance across test fixtures

## Risks

1. **Notification service not yet built**: this handler depends on `event-platform`.
   Cannot be built until that dependency ships. Mitigate: design to the notification
   service's public API contract from its requirements/plan.
2. **Over-rewriting human-authored plans**: mitigate with bounded edits, uncertainty
   boundary, and explicit blocker recording.
3. **False confidence from inflated scores**: mitigate with structured rubric and
   plan-requirement consistency checking.
4. **Handler complexity**: the handler combines assessment, improvement, and resolution.
   Mitigate: separate scorer, improver, and reporter into distinct modules.

## Exit criteria

1. Handler runs as part of daemon, consuming todo lifecycle events.
2. DOR reports are written for assessed todos with correct score/verdict.
3. Notifications are resolved (or left unresolved for needs_decision).
4. Idempotency prevents redundant assessments.
5. Tests pass, lint passes.

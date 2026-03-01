# Implementation Plan: Prepare Quality Runner

## Overview

Deliver a pipeline cartridge that reacts to todo lifecycle events, scores DOR quality
using a deterministic rubric, performs lightweight structural improvements, and writes
assessment results to todo artifacts.

The cartridge sits in the event platform pipeline after system cartridges (dedup,
notification projector). It is the first domain-logic cartridge in the codebase.

## Phase 1: Cartridge & Event Filtering

### Task 1.1: Create cartridge module

**File(s):** `teleclaude_events/cartridges/prepare_quality.py` (new)

- [ ] Implement `PrepareQualityCartridge` class with `Cartridge` protocol:
  - `name = "prepare-quality"`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`
- [ ] Filter: only process `domain.software-development.planning.*` events.
  Pass through all other events immediately.
- [ ] Extract slug from `event.payload["slug"]`.
- [ ] Skip if slug is in `todos/delivered.yaml` or `todos/icebox.md`.
- [ ] Always return the event (pass-through for downstream cartridges).

**Verification:** Cartridge passes through non-planning events unchanged. Planning
events trigger processing.

### Task 1.2: Idempotency check

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] Compute current git commit hash of `todos/{slug}/` folder via
  `git log -1 --format=%h -- todos/{slug}/`.
- [ ] Read `state.yaml` dor section. If `assessed_commit` matches and `status == pass`,
  skip processing. Log skip reason.
- [ ] If different commit or no prior assessment, proceed.

**Verification:** Duplicate event for unchanged slug is skipped. Changed slug is processed.

## Phase 2: DOR Scoring Engine

### Task 2.1: Rubric scorer

**File(s):** `teleclaude_events/cartridges/prepare_quality.py` (scorer as internal module
or separate file `teleclaude_events/cartridges/dor_scorer.py` — builder's choice)

- [ ] Define scoring rubric as structured criteria:
  - Requirements dimensions:
    - Intent clarity (0-2): problem statement and outcome explicit?
    - Scope atomicity (0-2): fits one session? Cross-cutting called out?
    - Success criteria (0-2): concrete, testable? Not "works" or "better"?
    - Dependency correctness (0-1): prerequisites listed? Roadmap aligned?
    - Constraint specificity (0-1): boundaries clear? Integration safety addressed?
  - Plan dimensions:
    - Concrete file targets (0-2): specific files/paths named?
    - Verification steps (0-2): each task has a check?
    - Risk identification (0-1): risks listed with mitigations?
    - Task-to-requirement traceability (0-2): every task maps to a requirement?
    - Plan-requirement consistency (0-1): no contradictions?
  - Maximum: 16 raw points → normalized to 1..10 scale.
- [ ] `score_requirements(content: str) -> dict` with per-dimension scores and gaps.
- [ ] `score_plan(content: str, requirements: str) -> dict` with per-dimension scores.
- [ ] Combine into overall DOR score with verdict:
  - >= 8 → `pass`
  - < 8 with improvable gaps → `needs_work`
  - < 7 with no safe improvements → `needs_decision`

**Verification:** Unit tests for scoring thresholds across fixture todos.

### Task 2.2: Plan-requirement consistency check

**File(s):** Same as 2.1.

- [ ] Parse plan tasks (markdown checkboxes / section headers).
- [ ] Parse requirements sections (FR1..FRn).
- [ ] Flag plan tasks that reference no requirement.
- [ ] Flag contradictions where plan prescribes opposite of requirement.
- [ ] Contradictions are `needs_work` blockers.

**Verification:** Fixture with contradicting plan/requirement produces `needs_work`.

## Phase 3: Lightweight Improvement

### Task 3.1: Structural gap filler

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] When requirements.md is missing dependency section: add from `roadmap.yaml`.
- [ ] When plan is missing verification steps: add "**Verification:** TBD" placeholders.
- [ ] When requirements are missing constraint section: flag gap in report.
- [ ] Do NOT rewrite prose or change technical approach.
- [ ] Return list of edits made.

**Verification:** Missing structural sections are filled. Prose is untouched.

### Task 3.2: Post-improvement reassessment

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] After structural improvements, re-run scorer on updated content.
- [ ] Update score and verdict.
- [ ] If still below threshold: verdict is final.

**Verification:** Improved artifact rescores higher. Still-weak artifact stays at lower score.

## Phase 4: Output & State

### Task 4.1: DOR report writer

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] Write `todos/{slug}/dor-report.md` with template:
  - Score + verdict
  - Assessment timestamp
  - Assessed commit hash
  - Per-dimension scores
  - Edits performed (if any)
  - Remaining gaps
  - Blockers / decisions needed

**Verification:** Report matches scoring result for fixture todos.

### Task 4.2: State writeback

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] Read existing `state.yaml` and update dor section:
  - `last_assessed_at`, `score`, `status`, `schema_version`, `blockers`,
    `actions_taken`, `assessed_commit`
- [ ] Preserve all non-dor keys in `state.yaml`.
- [ ] Use YAML safe dump with consistent formatting.

**Verification:** `state.yaml` dor section matches schema. Non-dor keys preserved.

### Task 4.3: Notification lifecycle

**File(s):** `teleclaude_events/cartridges/prepare_quality.py`

- [ ] Look up notification row from `context.db` by idempotency key or group key
  (slug) from the event.
- [ ] Claim: `context.db.update_agent_status(id, "claimed", "prepare-quality-runner")`.
- [ ] On `pass` or `needs_work`: resolve via `context.db.resolve_notification(id, resolution)`.
- [ ] On `needs_decision`: leave unresolved. Log blockers.
- [ ] Emit `domain.software-development.planning.dor_assessed` event via producer
  (requires producer reference — either passed via context or imported from module-level).

**Verification:** Notification resolved for pass/needs_work. Unresolved for needs_decision.

## Phase 5: Pipeline Wiring

### Task 5.1: Add cartridge to daemon pipeline

**File(s):** `teleclaude/daemon.py`

- [ ] Import `PrepareQualityCartridge` from `teleclaude_events.cartridges.prepare_quality`.
- [ ] Add to pipeline construction after system cartridges:
  ```python
  pipeline = Pipeline(
      [DeduplicationCartridge(), NotificationProjectorCartridge(), PrepareQualityCartridge()],
      context,
  )
  ```
- [ ] Cartridge lifecycle follows daemon lifecycle (no special start/stop needed).

**Verification:** Daemon startup logs show three cartridges. Event emission triggers assessment.

### Task 5.2: Export from cartridges package

**File(s):** `teleclaude_events/cartridges/__init__.py`

- [ ] Add `PrepareQualityCartridge` to package exports.

**Verification:** Import works from both daemon and tests.

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Unit tests for DOR scorer (rubric evaluation, threshold mapping).
- [ ] Unit tests for idempotency (skip logic, commit hash comparison).
- [ ] Unit tests for structural improver (gap filling, prose preservation).
- [ ] Integration test: create pipeline with all three cartridges, feed a planning event,
  verify DOR report written and state updated.
- [ ] Test `needs_decision` path: notification left unresolved.
- [ ] Run `make test`.

### Task 6.2: Quality checks

- [ ] Run `make lint`.
- [ ] Verify cartridge does not import daemon internals (only `teleclaude_events`).
- [ ] Verify `state.yaml` schema compliance across test fixtures.
- [ ] Verify pipeline pass-through: non-planning events are unaffected.

## Risks

1. **Assessment latency**: File I/O + scoring in the pipeline loop could slow event
   processing. Mitigate: measure per-slug processing time, log warnings > 2s.
   If latency proves problematic, move to async task dispatch in a future iteration.
2. **Deterministic scoring limitations**: Rubric-based scoring may miss nuanced quality
   issues that AI assessment would catch. Mitigate: this is v1. AI-powered assessment
   can be layered on in a future iteration by dispatching an agent session for
   improvement-heavy cases.
3. **Concurrent assessment**: Two events for the same slug arriving close together could
   cause concurrent writes. Mitigate: idempotency check + `state.yaml` as optimistic
   lock (read before write, check assessed_commit).

## Exit criteria

1. Cartridge runs in the daemon pipeline, processing todo lifecycle events.
2. DOR reports are written for assessed todos with correct score/verdict.
3. Notifications are resolved (or left unresolved for needs_decision).
4. Idempotency prevents redundant assessments.
5. Tests pass, lint passes.
6. Pipeline pass-through verified for non-planning events.

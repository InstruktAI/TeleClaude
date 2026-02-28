# Requirements: Prepare Quality Runner

## Goal

Implement an event-driven notification handler that reacts to todo lifecycle events and
maintains preparation quality. The handler consumes events from the notification service,
assesses todo readiness using the DOR criteria, improves preparation artifacts when safe,
and resolves the triggering notification with the assessment result.

This is TeleClaude's first internal dog-fooding consumer of the notification service.

## Scope

### In scope

1. Notification handler that consumes todo lifecycle events from the notification service.
2. DOR assessment logic: score each todo's `requirements.md` and `implementation-plan.md`
   against the Definition of Ready criteria.
3. Safe autonomous improvement of weak preparation artifacts.
4. DOR report output (`dor-report.md`) with score, verdict, edits, and gaps.
5. State writeback (`state.yaml` dor section) with structured assessment metadata.
6. Notification resolution: attach DOR score + verdict to the triggering notification.
7. Idempotency: same slug + same commit hash = no-op (skip already-assessed state).

### Out of scope

- Implementing product features from todos.
- Modifying delivered/icebox items.
- Re-prioritizing roadmap order.
- Inventing architecture decisions by guessing.
- Producing or consuming events outside the todo lifecycle domain.

## Dependency

This handler depends on `event-platform` being operational. It consumes events
via the notification service's Redis Stream consumer infrastructure and resolves
notifications through the notification API.

## Functional requirements

### FR1: Event consumption

- Register as a notification handler for the following event types:
  - `todo.artifact_changed` — requirements.md or implementation-plan.md modified
  - `todo.created` — new todo scaffolded (if requirements or plan exist)
  - `todo.dumped` — brain dump via `telec todo dump`
  - `todo.activated` — moved from icebox to active roadmap
  - `todo.dependency_resolved` — a blocking dependency was delivered
- Claim the notification via the notification API before starting assessment.
- Skip events for slugs in `todos/delivered.yaml` or `todos/icebox.md`.

### FR2: Idempotency

- Derive idempotency from slug + commit hash of the todo folder.
- If `state.yaml` dor section shows the same commit was already assessed with
  `status == pass`, skip processing and resolve the notification as no-op.
- If the slug's artifacts changed since last assessment, proceed with reassessment.

### FR3: Artifact assessment

- Evaluate `requirements.md` for: intent clarity, scope atomicity, testable success
  criteria, dependency correctness, constraint specificity.
- Evaluate `implementation-plan.md` for: concrete file targets, verification steps,
  risk identification, task-to-requirement traceability.
- Treat `input.md` as optional context that informs but does not replace requirements.
- Detect plan-to-requirement contradictions (e.g., plan prescribes copying when
  requirements say reuse).

### FR4: DOR scoring and verdict

- Score each todo on `1..10`.
- Thresholds:
  - `pass`: score >= 8
  - `needs_work`: score < 8 and artifacts can be improved safely
  - `needs_decision`: score < 7 and safe improvement is exhausted
- Record score, status, blockers, and actions taken in `state.yaml` dor section.

### FR5: Autonomous improvement

- When score < 8 and gaps are concrete and grounded:
  - Fill missing preparation files using codebase context.
  - Tighten weak sections (vague criteria, missing verification steps, unclear scope).
  - Add dependency references when discoverable from `roadmap.yaml`.
- Do not invent behavior or architecture outside known context.
- Stop and flag `needs_decision` when uncertainty becomes blocking.
- After improvement, reassess and update score.

### FR6: DOR report output

- Write `todos/{slug}/dor-report.md` after each assessment.
- Report must include:
  - Score + verdict
  - Edits performed (if any)
  - Remaining gaps
  - Stop reason when applicable
  - Specific decisions needed (for `needs_decision`)

### FR7: State writeback

- Write/update `state.yaml` dor section with:
  - `last_assessed_at` (ISO 8601)
  - `score` (1..10)
  - `status` (`pass`, `needs_work`, `needs_decision`)
  - `schema_version` (1)
  - `blockers` (list of strings)
  - `actions_taken` (object with boolean fields)
  - `assessed_commit` (short commit hash of todo folder at assessment time)

### FR8: Notification resolution

- On assessment completion, resolve the triggering notification via the notification API.
- Attach structured resolution:
  - `summary`: one-line DOR verdict (e.g., "DOR pass (8/10) for prepare-quality-runner")
  - `resolved_by`: handler identity
  - `resolved_at`: ISO 8601 timestamp
- If `needs_decision`: do NOT resolve the notification. Leave it unresolved so
  it remains visible as a signal for human attention.

## Non-functional requirements

1. Async-first: all I/O operations must be async, consistent with the codebase.
2. Idempotent reruns when nothing changed.
3. No destructive operations on unrelated files.
4. Clear audit trail in every touched todo.
5. Handler must be registerable with the notification service's event catalog.

## Acceptance criteria

1. Handler processes a `todo.artifact_changed` event and produces a DOR report.
2. Handler resolves the notification with score + verdict on `pass` or `needs_work`.
3. Handler leaves notification unresolved on `needs_decision` with explicit blockers.
4. Idempotency: duplicate event for same slug + same commit is skipped.
5. A weak todo is improved and rescored above threshold.
6. An ambiguous todo is flagged `needs_decision` with specific blockers.
7. `state.yaml` dor section matches the schema contract.
8. `make test` passes with tests covering event consumption, scoring, and resolution.
9. `make lint` passes.

## Constraints

- Must use the notification service API for event consumption and resolution.
  Direct Redis Stream access is not allowed — the notification service owns the stream.
- Must not import from `teleclaude_notifications.*` internals. Use only the public API
  (producer `emit`, API endpoints for claim/resolve).
- The handler runs within the daemon process, hosted alongside the notification processor.

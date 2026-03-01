# Requirements: Prepare Quality Runner

## Goal

Implement a pipeline cartridge that reacts to todo lifecycle events, assesses DOR quality,
improves preparation artifacts when safe, and writes assessment results to the todo folder.

The cartridge integrates with the event platform's `Pipeline` as a registered processing
step. It runs after dedup and notification projection, operating on events that survived
the system cartridges.

This is TeleClaude's first domain-logic cartridge — it proves the pattern before
other domain cartridges follow.

## Scope

### In scope

1. Pipeline cartridge in `teleclaude_events/cartridges/` implementing the `Cartridge` protocol.
2. DOR assessment logic: score `requirements.md` and `implementation-plan.md` against
   the Definition of Ready criteria using a structured rubric.
3. Safe autonomous improvement of weak preparation artifacts (within the cartridge process).
4. DOR report output (`dor-report.md`) with score, verdict, edits, and gaps.
5. State writeback (`state.yaml` dor section) with structured assessment metadata.
6. Notification lifecycle integration: claim/resolve notifications via `EventDB` when
   the cartridge processes relevant events.
7. Idempotency: same slug + same commit hash = skip (already assessed).

### Out of scope

- Implementing product features from todos.
- Modifying delivered/icebox items.
- Re-prioritizing roadmap order.
- Inventing architecture decisions by guessing.
- Producing or consuming events outside the todo lifecycle domain.
- AI-powered artifact rewriting (deferred to a future iteration; this version uses
  deterministic rubric scoring and lightweight structural improvements only).

## Dependency

The event platform core is delivered. This cartridge depends on:
- `teleclaude_events.pipeline.Cartridge` protocol
- `teleclaude_events.pipeline.PipelineContext` (catalog, db, push_callbacks)
- `teleclaude_events.envelope.EventEnvelope`
- `teleclaude_events.db.EventDB` for notification state operations
- `teleclaude_events.catalog.EventCatalog` for schema lookups

All of these are shipped and stable.

## Functional requirements

### FR1: Cartridge integration

- Implement `Cartridge` protocol: `name: str`, `async def process(self, event, context) -> EventEnvelope | None`.
- Filter for `domain.software-development.planning.*` events only. Pass through all others.
- Event types consumed:
  - `domain.software-development.planning.artifact_changed`
  - `domain.software-development.planning.todo_created`
  - `domain.software-development.planning.todo_dumped`
  - `domain.software-development.planning.todo_activated`
  - `domain.software-development.planning.dependency_resolved`
- Always return the event (pass-through) so downstream cartridges still run.
- The cartridge runs after `DeduplicationCartridge` and `NotificationProjectorCartridge`
  in the pipeline.

### FR2: Idempotency

- Derive idempotency from slug + git commit hash of the `todos/{slug}/` folder.
- If `state.yaml` dor section shows the same commit was already assessed with
  `status == pass`, skip processing.
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

### FR5: Lightweight improvement

- When score < 8 and gaps are structural (missing sections, missing dependency refs):
  - Add missing roadmap dependency references when discoverable from `roadmap.yaml`.
  - Add missing verification sections to implementation plan.
  - Flag missing requirements sections.
- Do not rewrite prose, invent behavior, or change technical approach.
- Stop and flag `needs_decision` when improvement requires judgment.
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

### FR8: Notification lifecycle

- After assessment, update the notification row via `EventDB`:
  - Claim via `update_agent_status(id, "claimed", "prepare-quality-runner")` at start.
  - Resolve via `resolve_notification(id, resolution)` on `pass` or `needs_work`.
  - Leave unresolved on `needs_decision`.
- The notification ID comes from the `NotificationProjectorCartridge` having already
  projected the event. The cartridge looks up the notification by idempotency key or
  group key from the DB.
- Emit `domain.software-development.planning.dor_assessed` event via the producer
  after assessment, carrying score and verdict in payload.

## Non-functional requirements

1. Async-first: all I/O operations must be async, consistent with the codebase.
2. Idempotent reruns when nothing changed.
3. No destructive operations on unrelated files.
4. Clear audit trail in every touched todo.
5. Pipeline pass-through: the cartridge must always return the event so downstream
   processing is not broken.

## Acceptance criteria

1. Cartridge processes a `planning.artifact_changed` event and produces a DOR report.
2. Notification row shows `agent_status=resolved` on `pass` or `needs_work`.
3. Notification row stays unresolved on `needs_decision` with explicit blockers.
4. Idempotency: duplicate event for same slug + same commit is skipped.
5. A weak todo has structural gaps filled and rescores above threshold.
6. An ambiguous todo is flagged `needs_decision` with specific blockers.
7. `state.yaml` dor section matches the schema contract.
8. `make test` passes with tests covering cartridge processing, scoring, and resolution.
9. `make lint` passes.
10. Pipeline integration: adding the cartridge to the daemon pipeline does not break
    existing event processing.

## Constraints

- Must implement the `Cartridge` protocol from `teleclaude_events.pipeline`.
- Must not access Redis directly — all event data arrives via the `process()` method.
- Must not import daemon internals. Only use `teleclaude_events` public surface.
- The cartridge runs in the daemon's event processing loop. Keep processing fast —
  if assessment for a single slug takes > 2s, log a warning.
- File I/O (reading todo artifacts) is acceptable within the cartridge since the
  pipeline runs in the daemon process with filesystem access.

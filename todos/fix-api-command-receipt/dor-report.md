# DOR Report (Gate): fix-api-command-receipt

## Final Gate Verdict

- Status: `needs_work`
- Score: `7/10`
- Ready Decision: **Not Ready**
- Assessed commit: `374c0d30bc559c549be44452a722fb1308fff3f4`

This gate was grounded against the current preparation policies plus the live
API server, operation-receipts, Redis transport, command-surface,
layer-ownership, and session-lifecycle specs. It was assessed from the
worktree `trees/fix-api-command-receipt`, because that is where the
expected-failure spec tests for this todo live. The artifact set is still not
coherent enough to dispatch a builder safely: the xfail specs exist but are
not review-ready, the lifecycle record still does not fully reflect that spec
phase, FR-2 is still contradicted by the plan, and the dependency/demo
artifacts do not yet present one stable response-mode contract.

## Cross-Artifact Validation

### Plan-to-requirement fidelity: FAIL

- FR-2 says adding a new command subclass must require no dispatcher changes.
  Task 2 still centers `teleclaude/transport/redis_transport/_messaging.py`
  on a per-`CommandType` handler table, and the demo repeats that model
  ("adding a table entry"). That satisfies metadata-driven execution mode,
  but not the requirement as written.
- The requirements and acceptance criteria preserve the current 200 contract
  for `POST /sessions/{id}/message`, `/keys`, `/voice`, and
  `/sessions/self/file`, but `demo.md` still asserts
  `ProcessMessageCommand` is `FIRE_AND_FORGET`. The artifacts do not yet
  expose one canonical API contract.
- `requirements.md` says `web-tui-parity` must land first "per roadmap.yaml",
  but `todos/roadmap.yaml` has no `after:` dependency for this slug.

### Coverage completeness: PASS

- FR-1 through FR-6 each have one or more corresponding plan tasks.
- The plan covers the full input audit surface: response-mode plumbing,
  dispatcher refactor, receipt-backed `todo_create` / `todo_prepare`,
  missing domain events, typed command wrapping, DELETE remote routing,
  and the four architecture-doc updates.
- The worktree contains expected-failure spec tests for FR-1 through FR-6
  under `tests/unit/core/`.
- `state.yaml.grounding.referenced_paths` matches the implementation surface
  named in the plan, so the artifact set is grounded in real code paths.

### Verification chain: FAIL

- Expected-failure specs now exist in the worktree, but they are not gate-ready:
  - `test_spec_review.verdict` is `needs_work`.
  - `spec-review-findings.md` records four critical gaps across FR-2 through FR-5.
  - `artifacts.test_specs.produced_at` is still empty, so the lifecycle record
    does not yet confirm spec delivery.
- `implementation-plan.md` still references generic behavioral checks rather than
  the concrete xfail test files it is supposed to make GREEN, so builder
  verification remains underspecified.
- `telec todo demo validate fix-api-command-receipt` passes structurally with
  8 executable blocks, but `demo.md` is semantically stale on command
  classification, so it is not yet trustworthy review evidence.

## DOR Gate Results

### 1. Intent & success: PASS

`input.md` and `requirements.md` state both the problem and the target outcome
clearly: mutating endpoints must derive behavior from declared response modes,
long-running mutations must move to the receipt pattern, and async mutations
must emit domain events for completion or acceptance.

### 2. Scope & size: PASS

This is still one coherent behavior slice. The work is broad, but the breadth
stays inside one architecture change: response-mode alignment across command
objects, dispatch, selected routes, operations, and docs. The input and plan
are detailed enough that further splitting would add coordination cost without
reducing meaningful discovery risk.

### 3. Verification: FAIL

Definition of Ready requires executable expected-failure test specifications
for all behavioral requirements. Those specs now exist in the worktree, but
the test-spec review verdict is still `needs_work`, the lifecycle stamp for
`artifacts.test_specs.produced_at` is missing, and the current plan is not
yet tied to the concrete xfail files. Until the spec artifact is both
recorded and approved, this gate fails.

### 4. Approach known: PASS

The technical path is concrete and grounded in the current code:

- `POST /sessions/{id}/message`, `/keys`, `/voice`, and `/sessions/self/file`
  still await `CommandService` methods and return synchronous 200 responses,
  which matches the requirements' "already correct" bucket.
- `POST /sessions/{id}/agent-restart` currently uses `asyncio.create_task()`
  and returns `{"status": "accepted"}`, `POST /jobs/{name}/run` uses
  `BackgroundTasks`, and `DELETE /sessions/{id}` already performs an accepted
  lifecycle handoff. Those are the real fire-and-forget surfaces the plan is
  trying to formalize.
- `POST /todos/work` and `/todos/integrate` already use `OperationsService`
  receipts, while `todo_create()` and `todo_prepare()` are still synchronous in
  `teleclaude/api/todo_routes.py`, so the receipt-extension path is grounded in
  an existing pattern.
- `OperationStatusDTO` currently lacks `completion_event`, and
  `teleclaude/core/events.py` does not yet define the new domain payloads,
  matching the gaps the plan intends to close.

The remaining issues are coherence and readiness, not lack of code grounding.

### 5. Research complete: PASS

No new third-party tooling or external integration research is required. The
todo extends existing FastAPI, Redis transport, event bus, and operation-
receipt patterns already present in the repo.

### 6. Dependencies & preconditions: FAIL

The dependency story is not trustworthy as written:

- `requirements.md` says `web-tui-parity` must be delivered first per the
  roadmap.
- `todos/roadmap.yaml` does not encode that dependency.

That inconsistency must be resolved before build scheduling.

### 7. Integration safety: PASS

The plan keeps the change set bounded to known command, API, operations,
event, and docs surfaces. The riskiest areas are called out explicitly, and
the work can be delivered in one builder branch without requiring new
infrastructure, feature flags, or partial-production rollout mechanics.

### 8. Tooling impact: PASS

No scaffolding, generator, CLI-surface, or configuration-wizard changes are in
scope. This gate is automatically satisfied.

## Review-Readiness Preview

- Test lane: not ready. The xfail specs exist, but `test_spec_review` is still
  `needs_work`; the recorded findings say FR-2 does not pin the real dispatcher
  boundary, FR-3 asserts receipt structure instead of the receipt contract,
  FR-4 mostly checks payload existence instead of emission, and FR-5 still uses
  AST/method-presence proxies instead of route-boundary assertions.
- API-contract lane: not ready. Requirements, plan, and demo disagree on the
  command classification for at least `ProcessMessageCommand`, and FR-2's
  "no dispatcher changes" language is not satisfied by the planned handler
  table inside `_dispatch_command()`.
- Dependency lane: not ready. The stale `web-tui-parity` prerequisite must be
  corrected either in `requirements.md` or in `todos/roadmap.yaml`.
- Demo lane: partially ready. Structural validation passes, but the demo needs
  semantic correction before it can be trusted as a review artifact.
- Builder guidance: not yet safe. A builder should not have to resolve which
  response-mode classification is canonical, whether Task 2 actually satisfies
  FR-2, or which concrete xfail spec file each task is expected to make GREEN.

## Unresolved Blockers

- Resolve the test-spec review findings, stamp the spec artifact in
  `state.yaml.artifacts.test_specs`, and rerun test-spec review until the
  verdict is `approve`.
- Reconcile FR-2 with Task 2: either relax the requirement wording or revise
  the plan so the dispatcher truly does not need per-command updates for new
  subclasses.
- Reconcile the response-mode classification across `requirements.md`,
  `implementation-plan.md`, and `demo.md`, especially for
  `ProcessMessageCommand` and the "already correct" 200 endpoints.
- Reconcile the stale `web-tui-parity` dependency claim with
  `todos/roadmap.yaml`.

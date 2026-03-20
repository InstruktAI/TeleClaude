# Implementation Plan: fix-api-command-receipt

## Overview

Add `ResponseMode` to the command type system and align all mutating API endpoints
with the command-classification design. The change flows through five layers:
type declarations → dispatch refactoring → operations service → domain events →
route responses. Documentation deliverables round out the work.

All tasks follow the target architecture defined in
`docs/project/design/architecture/command-classification.md` and extend the receipt
pattern from `docs/project/design/architecture/operation-receipts.md`.

**Test specifications:** Behavioral contracts listed in each task's verification
section are the input for the build-specs phase. The specs phase produces
expected-failure test files before the builder begins. Each task's verification
references the behavioral assertions those tests encode.

---

## Task 1: Add ResponseMode enum, base command fields, and subclass declarations

**What:** Add `ResponseMode` enum (`IMMEDIATE`, `FIRE_AND_FORGET`, `RECEIPT`) to
`teleclaude/types/commands.py`. Add `response_mode` and `completion_event` fields to
`InternalCommand.__init__`. Add construction-time validation inside `InternalCommand.__init__`
that raises `ValueError` when `response_mode` is `FIRE_AND_FORGET` and `completion_event`
is `None`. Then set `response_mode` defaults on each subclass `__init__` via
`super().__init__(... response_mode=ResponseMode.X, completion_event=...)`.

**Why:** The command-classification design makes the mode a property of the command
object, not the route. Without this field, routes must hardcode status codes and the
dispatcher must use isinstance chains. Validation belongs in `__init__` (not
`__post_init__`) because all command subclasses use handwritten `__init__` methods
that call `super().__init__()` — the codebase has no dataclass-generated initializers
for commands, so `__post_init__` would never fire.

Classification table (derived from the design doc, requirements, and current endpoint
behavior). The governing rule: endpoints the input marks "already correct" retain their
current response codes and shapes, so their commands are classified to match the existing
API contract.

| Command | Mode | completion_event |
|---------|------|-----------------|
| `CreateSessionCommand` | `IMMEDIATE` | `None` |
| `GetSessionDataCommand` | `IMMEDIATE` | `None` |
| `SystemCommand` | `IMMEDIATE` | `None` (default; instances may override) |
| `ProcessMessageCommand` | `IMMEDIATE` | `None` |
| `KeysCommand` | `IMMEDIATE` | `None` |
| `HandleVoiceCommand` | `IMMEDIATE` | `None` |
| `HandleFileCommand` | `IMMEDIATE` | `None` |
| `StartAgentCommand` | `IMMEDIATE` | `None` |
| `ResumeAgentCommand` | `IMMEDIATE` | `None` |
| `RunAgentCommand` | `IMMEDIATE` | `None` |
| `RestartAgentCommand` | `FIRE_AND_FORGET` | `"agent.restart_dispatched"` |
| `CloseSessionCommand` | `FIRE_AND_FORGET` | `"session.close_completed"` |

Note: `ProcessMessageCommand`, `KeysCommand`, `HandleVoiceCommand`, and
`HandleFileCommand` are classified `IMMEDIATE` because their API routes
(`POST /sessions/{id}/message`, `/keys`, `/voice`, `/file`) are marked "already
correct" in the input audit — they await the `CommandService` method and return 200.
The response_mode reflects the API contract, not internal execution detail.

`SystemCommand` defaults to `IMMEDIATE`. Task 5 constructs specific instances
(escalation) with `FIRE_AND_FORGET` and a `completion_event` override where the
wrapping changes the API contract.

Note: `RestartAgentCommand` is `FIRE_AND_FORGET`, not `IMMEDIATE`. The current
`POST /sessions/{id}/agent-restart` route dispatches via `asyncio.create_task()` and
returns `{"status": "accepted"}` — fire-and-forget behavior. The design doc currently
lists it under IMMEDIATE, which contradicts both the current behavior and FR-4. The
design doc will be corrected in Task 7.

**Files:**
- `teleclaude/types/commands.py` — add `ResponseMode` enum, add `response_mode` and
  `completion_event` parameters to `InternalCommand.__init__` with validation, pass
  defaults through `super().__init__()` in each subclass

**Verification:**
- Constructing a `FIRE_AND_FORGET` command with `completion_event=None` raises `ValueError`
- Each command subclass's `.response_mode` matches the classification table
- `IMMEDIATE` commands accept `completion_event=None` without error
- `CloseSessionCommand().completion_event` is `"session.close_completed"`
- `RestartAgentCommand().completion_event` is `"agent.restart_dispatched"`
- `SystemCommand` constructed with `response_mode=FIRE_AND_FORGET` and a `completion_event` succeeds
- Pre-commit hooks pass (existing payload tests in `tests/unit/types/test_commands.py` stay green)

---

## Task 2: Metadata-driven command dispatch (FR-2)

**What:** Refactor dispatch in `teleclaude/transport/redis_transport/_messaging.py`
`_dispatch_command()` (lines 339–365) into a two-layer architecture:

1. **Handler lookup layer:** A `dict[CommandType, Callable]` mapping `CommandType` →
   `CommandService` method. This replaces the isinstance chain for determining _which_
   handler to call. The CommandService already has explicit typed methods
   (`.create_session()`, `.process_message()`, etc.), so the table maps enum values to
   those existing methods.

2. **Execution mode layer:** After looking up the handler, the dispatcher reads
   `command.response_mode` to determine _how_ to execute:
   - `IMMEDIATE`: `result = await handler(command)` — await and return the result.
   - `FIRE_AND_FORGET`: `await handler(command)` — execute the handler (the redis
     transport always processes to completion), then return a minimal ack. The
     fire-and-forget semantics are expressed at the HTTP layer, not the transport layer.
   - `RECEIPT`: Should not reach the redis dispatcher — receipt commands go through
     `OperationsService` at the API layer. If encountered, raise `ValueError`.

For Telegram adapter (`teleclaude/adapters/telegram/private_handlers.py`, lines 279–299):
the two isinstance checks (`KeysCommand` → special key dispatch, `CloseSessionCommand` →
special close dispatch) become `command_type == CommandType.KEYS` and
`command_type == CommandType.CLOSE_SESSION`. This is a minimal change —
the adapter still needs to route these two types specially for its UX.

**Why:** FR-2 requires that "adding a new command subclass requires no changes to the
dispatcher." The current isinstance chains violate this — every new command type requires
a new branch. The two-layer design satisfies FR-2 because:
- Adding a new command with an existing response_mode requires only a handler table entry.
- The execution behavior (await vs. ack) derives automatically from `response_mode`.
- The dispatcher never inspects the command class — it reads declared metadata.

A `command_type`-only dispatch table (without the response_mode layer) would still
require dispatcher edits when a new command type changes execution semantics.
The response_mode layer makes execution behavior declarative.

**Files:**
- `teleclaude/transport/redis_transport/_messaging.py` — replace `_dispatch_command`
  isinstance chain with handler table + response_mode execution branches
- `teleclaude/adapters/telegram/private_handlers.py` — replace isinstance checks with
  `command_type` comparisons

**Verification:**
- Redis transport dispatch resolves handler via `command_type` lookup, not isinstance
- Redis transport execution branches on `command.response_mode`, not command class
- `IMMEDIATE` dispatch awaits handler and returns its result
- `FIRE_AND_FORGET` dispatch awaits handler and returns minimal ack
- `RECEIPT` command reaching dispatch raises `ValueError`
- Telegram adapter routes `CommandType.KEYS` and `CommandType.CLOSE_SESSION` to their
  special handlers without isinstance
- No isinstance chains for command type routing remain in dispatch code
- Pre-commit hooks pass

---

## Task 3: Receipt-backed operations for todo create and prepare (FR-3)

**What:** Three changes:

**3a. Operation kind constants and submit methods.** Add `OPERATION_KIND_TODO_CREATE`
and `OPERATION_KIND_TODO_PREPARE` constants to `teleclaude/core/operations/service.py`.
Add `submit_todo_create()` and `submit_todo_prepare()` methods following the existing
`submit_todo_work()` pattern (lines 105–174 are the template). Add
`_run_todo_create_operation()` and `_run_todo_prepare_operation()` background runners
that call `next_create()` and `next_prepare()` respectively. Extend
`_ensure_operation_task()` (line 278) to handle the new kinds.

**3b. completion_event on receipt DTOs and terminal transition.** Add
`completion_event: str | None` field to:
- `OperationStatusDTO` in `teleclaude/api_models.py`
- `OperationStatusPayload` TypedDict in `teleclaude/api_models.py`
- `SerializedOperation` TypedDict in `teleclaude/core/operations/service.py`

Populate `completion_event` in `_serialize_operation()` from the operation's kind
(each kind maps to a fixed completion event name). The operation-receipts design doc
requires that terminal transitions emit `completion_event` atomically with the DB row
write. Add `event_bus.emit()` calls at the terminal write points in
`_run_todo_work_operation()`, `_run_todo_create_operation()`, `_run_todo_prepare_operation()`,
and `_run_todo_integrate_operation()` — including the two existing runners that currently
lack emission.

**3c. Route updates.** Update `teleclaude/api/todo_routes.py` routes: change
`POST /todos/create` (line 58) and `POST /todos/prepare` (line 75) to return `202`
with `OperationStatusDTO` response model, wiring to the new `OperationsService` submit
methods. Add `client_request_id` and caller identity parameters matching the existing
`todo_work()` route pattern (lines 92–115).

**Why:** The input audit identifies `todo_create` and `todo_prepare` as heavy synchronous
endpoints that block the HTTP connection while running full state machines. The receipt
pattern (persist-before-execute, atomic terminal transition, stale-on-restart) already
works for `todo_work` and `todo_integrate`. Extending it is mechanical — same
submit/lock/dedup/runner pattern, different coroutine.

The completion_event field is required by both the operation-receipts design doc
(terminal transition MUST emit completion_event) and the command-classification design
doc (RECEIPT responses carry completion_event for consumer subscription). Without it,
the receipt contract is structurally incomplete — consumers have no way to subscribe
for operation completion.

**Files:**
- `teleclaude/core/operations/service.py` — add kind constants, submit methods,
  background runners, extend `_ensure_operation_task` kind routing, add
  `completion_event` to `SerializedOperation` and `_serialize_operation()`, add
  event emission at terminal write points for all operation kinds
- `teleclaude/api_models.py` — add `completion_event` field to `OperationStatusDTO`
  and `OperationStatusPayload`
- `teleclaude/api/todo_routes.py` — update `todo_create()` and `todo_prepare()` routes
  to return 202 receipts via OperationsService

**Verification:**
- `submit_todo_create()` persists an operation row and returns a receipt with `operation_id`
  and `completion_event`
- `submit_todo_prepare()` persists an operation row and returns a receipt with `completion_event`
- Duplicate `client_request_id` for todo_create reattaches to existing operation
- `_ensure_operation_task` dispatches correct runner for `OPERATION_KIND_TODO_CREATE`
- `POST /todos/create` returns HTTP 202 with `OperationStatusDTO` shape including
  `completion_event` field
- `POST /todos/prepare` returns HTTP 202 with `OperationStatusDTO` shape including
  `completion_event` field
- Terminal transition for all operation kinds emits completion_event via event_bus
- `OperationStatusDTO` serialization includes `completion_event` for all kinds
- Existing mark-phase, set-deps, work, integrate routes unchanged (no regression)
- Pre-commit hooks pass

---

## Task 4: Domain events for fire-and-forget mutations (FR-4) and missing notification events

**What:** Add frozen domain event payload dataclasses to `teleclaude/core/events.py`
following the existing pattern (`SessionLifecycleContext`, `AgentActivityEvent`):

1. `AgentRestartDispatchedEvent` — emitted after successful restart dispatch in
   `teleclaude/core/command_handlers/_agent.py` `agent_restart()` (line 207)
2. `SessionCloseCompletedEvent` — emitted when close processing finishes in
   `teleclaude/core/command_handlers/_session.py` `close_session()` (line 606)
3. `SessionEscalationStartedEvent` — emitted after thread creation + DB update in
   the escalation handler (currently inline in `sessions_actions_routes.py`, will be
   in the SystemCommand handler after Task 5)
4. `JobLifecycleEvent` — emitted from `teleclaude/api/jobs_routes.py` `run_job()`
   (line 81) background wrapper: started on entry, completed/failed on exit
5. `NotificationClaimedEvent` — emitted when a notification is claimed (the existing
   `POST /api/notifications/{id}/claim` endpoint)
6. `NotificationResolvedEvent` — emitted when a notification is resolved (the existing
   `POST /api/notifications/{id}/resolve` endpoint)

Each event dataclass is `@dataclass(frozen=True)` with typed fields carrying enough
context for correlation (session_id, job name, notification_id, etc.). Events are
emitted via `event_bus.emit()` at the point where the mutation succeeds.

**Why:** The command-classification design requires `completion_event` on all
FIRE_AND_FORGET commands. Task 1 declares these event names on the command objects.
Without corresponding emissions, the contract is broken — the event name exists but
is never published. The notification events (req-002) close the gap between input.md's
event list and the requirements.

**Files:**
- `teleclaude/core/events.py` — add new frozen event payload dataclasses, extend
  `EventType` literal if needed
- `teleclaude/core/command_handlers/_agent.py` — emit `AgentRestartDispatchedEvent`
  after successful restart dispatch
- `teleclaude/core/command_handlers/_session.py` — emit `SessionCloseCompletedEvent`
  at end of close processing
- `teleclaude/api/jobs_routes.py` — emit `JobLifecycleEvent` (started/completed/failed)
  from the background task wrapper
- `teleclaude/api/notifications_routes.py` — emit `NotificationClaimedEvent` from
  `claim_notification` endpoint and `NotificationResolvedEvent` from
  `resolve_notification` endpoint

**Verification:**
- `agent_restart` handler emits `AgentRestartDispatchedEvent` after successful dispatch
- `close_session` handler emits `SessionCloseCompletedEvent` when processing completes
- `run_job` background wrapper emits started event on entry and completed/failed on exit
- `claim_notification` endpoint emits `NotificationClaimedEvent` with `notification_id`
- `resolve_notification` endpoint emits `NotificationResolvedEvent` with `notification_id`
- All new event payloads are frozen dataclasses with typed fields
- Pre-commit hooks pass

---

## Task 5: Typed command wrapping for inline mutations and DELETE /sessions coverage (FR-5 + req-001)

**What:** Two changes: wrap inline mutations in the SystemCommand pattern, and resolve
the SystemCommand dispatch seam.

**5a. SystemCommand dispatch seam.** Add a `system_command()` method to
`teleclaude/core/command_service.py` that accepts a `SystemCommand` and routes based
on `cmd.command` field value. The current `SystemCommandContext` event path
(`teleclaude/core/events.py:437`) is daemon-level (cross-computer system commands),
not session mutation delivery. The new `CommandService.system_command()` method handles
session-scoped SystemCommand operations:
- `"deliver_result"` → calls the adapter's `send_message()` (moves inline code from
  the route into the command handler)
- `"render_widget"` → calls the adapter's widget rendering (moves inline code)
- `"escalate_session"` → calls Discord adapter + DB update (moves inline code);
  emits `SessionEscalationStartedEvent` from Task 4

The routing is a simple `match cmd.command:` dispatch within the method. Each case
encapsulates the logic currently inline in the API route.

**5b. Endpoint wrapping.** Wrap endpoints that perform adapter/DB mutations inline:

1. `POST /sessions/self/result` (line 630) — construct
   `SystemCommand(command="deliver_result", response_mode=IMMEDIATE, ...)` and
   dispatch through `CommandService.system_command()`.
2. `POST /sessions/self/widget` (line 685) — construct
   `SystemCommand(command="render_widget", response_mode=IMMEDIATE, ...)`.
3. `POST /sessions/self/escalate` (line 719) — construct
   `SystemCommand(command="escalate_session", response_mode=FIRE_AND_FORGET,
   completion_event="session.escalation_started", ...)`.

Result and widget stay `IMMEDIATE` because they are synchronous adapter calls that
return data (message_id, summary). Escalation becomes `FIRE_AND_FORGET` because it
is categorized under fire-and-forget mutations in the input audit.

**5c. DELETE /sessions routing.** Route `DELETE /sessions/{id}`
(sessions_routes.py line 576) through `CommandService.end_session()` instead of
emitting `SESSION_CLOSE_REQUESTED` inline. The existing `end_session` handler
(`_session.py:626`) already handles the full close lifecycle. Check
`session.computer_name`: if it differs from the local computer, forward the
`CloseSessionCommand` via the existing remote transport mechanism rather than
handling locally.

**Why:** The input audit identifies result, widget, and escalate as command coverage
gaps — mutations that bypass the command system. Typed commands ensure audit trail,
consistent error handling, and response mode alignment.

The SystemCommand seam must be explicitly resolved because `CommandService` currently
has no `system_command()` method and the existing `SystemCommandContext` event path is
daemon-level (cross-computer). Leaving this "if needed" forces the builder to invent
the dispatch architecture, which is an architectural decision that belongs in the plan.

The DELETE /sessions gap (req-001) means the route currently handles close inline with
`event_bus.emit(SESSION_CLOSE_REQUESTED)` instead of going through the command system.
This leaves remote sessions unhandled — the `_computer` parameter exists but is ignored.

**Files:**
- `teleclaude/core/command_service.py` — add `system_command()` method with
  `match cmd.command:` dispatch for deliver_result, render_widget, escalate_session
- `teleclaude/api/sessions_actions_routes.py` — wrap result/widget/escalate inline
  adapter calls in SystemCommand dispatch through `CommandService.system_command()`
- `teleclaude/api/sessions_routes.py` — route DELETE /sessions through
  `CommandService.end_session()` with remote-routing check on `session.computer_name`
- `teleclaude/transport/redis_transport/_messaging.py` — add `CommandType.SYSTEM`
  entry to the handler dispatch table (Task 2) pointing to `CommandService.system_command()`

**Verification:**
- `CommandService.system_command()` exists and routes on `cmd.command` field
- `/sessions/self/result` dispatches through `CommandService.system_command()` and
  returns same observable response
- `/sessions/self/widget` dispatches through `CommandService.system_command()` and
  returns same observable response
- `/sessions/self/escalate` dispatches through `CommandService.system_command()` and
  returns 202 with `completion_event` (changed from 200 per fire-and-forget wrapping)
- `DELETE /sessions/{id}` uses `CloseSessionCommand` via `CommandService.end_session()`
- DELETE for a remote session (different `computer_name`) routes through transport,
  not local handler
- All result/widget endpoints still produce the same observable behavior (no regression)
- Pre-commit hooks pass

---

## Task 6: Route response code alignment

**What:** Update the small set of fire-and-forget API routes that are not "already
correct" to return `202 Accepted` with `{"status": "accepted", "completion_event": "<event>"}`
instead of their current response:

Routes changing to 202 with `completion_event`:
- `POST /sessions/{id}/agent-restart` (sessions_actions_routes.py:411) — currently
  returns 200 with `{"status": "accepted"}`; change to 202 and add `completion_event`
- `POST /jobs/{name}/run` (jobs_routes.py:80) — currently returns 200 with
  `{"status": "accepted", "job": "..."}` ; change to 202 and add `completion_event`
- `POST /sessions/self/escalate` — after Task 5 wrapping, returns 202 with
  `completion_event` (new endpoint behavior from FIRE_AND_FORGET SystemCommand)

Routes adding `completion_event` to existing 202 response:
- `DELETE /sessions/{id}` — already 202, add `completion_event` to response body

Routes explicitly NOT changing (already correct per input audit):
- `POST /sessions` (create session) — IMMEDIATE, stays 200
- `POST /sessions/run` — IMMEDIATE, stays 200
- `POST /sessions/{id}/message` — IMMEDIATE, stays 200
- `POST /sessions/{id}/keys` — IMMEDIATE, stays 200 (already correct)
- `POST /sessions/{id}/voice` — IMMEDIATE, stays 200 (already correct)
- `POST /sessions/self/file` — IMMEDIATE, stays 200 (already correct)
- `POST /sessions/self/result` — IMMEDIATE SystemCommand, stays 200
- `POST /sessions/self/widget` — IMMEDIATE SystemCommand, stays 200

The `completion_event` value for each route is read from the command object's
`completion_event` field (set in Task 1), not hardcoded in the route. This ensures
the route derives behavior from the command declaration per the design doc invariant.

**Why:** The command-classification design requires that HTTP status codes derive from
`response_mode`. `FIRE_AND_FORGET` → 202 with `completion_event` in the body. This
enables consumers to subscribe to the declared event for completion notification.

Only genuinely fire-and-forget endpoints change codes. The "already correct"
endpoints in the input audit retain their current 200 responses — their commands
are classified `IMMEDIATE` in Task 1 precisely to preserve this contract.

**Files:**
- `teleclaude/api/sessions_actions_routes.py` — update agent-restart route to 202 +
  completion_event
- `teleclaude/api/sessions_routes.py` — add `completion_event` to DELETE response body
- `teleclaude/api/jobs_routes.py` — update job run response to 202 + `completion_event`

**Verification:**
- `POST /sessions/{id}/agent-restart` returns HTTP 202 with `completion_event`
- `POST /jobs/{name}/run` returns HTTP 202 with `completion_event`
- `DELETE /sessions/{id}` returns HTTP 202 with `completion_event` in response body
- `POST /sessions/self/escalate` returns HTTP 202 with `completion_event` (via Task 5)
- Response body `completion_event` values match the command object's declaration
- All "already correct" endpoints still return HTTP 200 with unchanged response shapes
  (message, keys, voice, file, result, widget, create, run)
- Receipt endpoints still return HTTP 202 with full `OperationStatusDTO`
- Pre-commit hooks pass

---

## Task 7: Documentation deliverables (FR-6 / req-003)

**What:** Update four architecture design docs to reflect the implemented changes:

1. `docs/project/design/architecture/command-classification.md` — fix the
   `RestartAgentCommand` classification from IMMEDIATE to FIRE_AND_FORGET (line 84).
   Add the full endpoint-to-mode mapping table. Update the `InternalCommand` base
   fields code sample to match the implemented constructor pattern.

2. `docs/project/design/architecture/operation-receipts.md` — generalize from
   todo-specific to describe the pattern for any heavy async operation. Add
   `OPERATION_KIND_TODO_CREATE` and `OPERATION_KIND_TODO_PREPARE` to the kinds
   inventory. Document the `completion_event` field on receipt DTOs and the terminal
   emission contract.

3. `docs/project/design/architecture/api-server.md` (or create if not present) —
   add command classification table showing which endpoints fall in each bucket
   (IMMEDIATE / FIRE_AND_FORGET+EVENT / RECEIPT).

4. `docs/project/design/architecture/redis-transport.md` (or update existing) — add
   section on how `command.response_mode` determines whether the caller waits for
   `read_response` or fires-and-forgets.

**Why:** The input explicitly requires these four documentation updates as deliverables.
FR-6 captures this requirement. Architecture docs must reflect the implemented state,
not the pre-implementation design. The `RestartAgentCommand` correction prevents future
builders from implementing the wrong classification.

**Files:**
- `docs/project/design/architecture/command-classification.md`
- `docs/project/design/architecture/operation-receipts.md`
- `docs/project/design/architecture/api-server.md` (create or update)
- `docs/project/design/architecture/redis-transport.md` (update)

**Verification:**
- All four docs exist and reflect the implemented architecture
- `command-classification.md` lists `RestartAgentCommand` under FIRE_AND_FORGET
- `operation-receipts.md` covers all four operation kinds and documents `completion_event`
  on the receipt DTO
- `api-server.md` contains the full endpoint classification table
- Pre-commit hooks pass (doc formatting)

---

## Cross-cutting verification

After all tasks:
- Pre-commit hooks pass (lint, typecheck, tests — the primary verification path per testing policy)
- No isinstance chains for command type routing remain in dispatch code
- All FIRE_AND_FORGET commands have non-null `completion_event` (construction-time enforced)
- Receipt polling via `/operations/{id}` works for `todo_create` and `todo_prepare`
- Receipt responses include `completion_event` field
- Endpoints marked "already correct" and "leave as-is" in the input are unchanged
- All new domain events follow the existing frozen dataclass pattern
- Documentation reflects implemented state
- `demo.md` updated to cover user-visible API changes (response code changes, new
  receipt endpoints, completion_event in response bodies)

## Risks

- **Regression surface (Task 2 + Task 6):** Refactoring dispatch and changing response
  codes touches command processing. Mitigation: two-layer dispatch is a mechanical
  replacement — same methods, same execution outcomes, different lookup. Response code
  changes only affect 3 endpoints (agent-restart, jobs/run, escalation), none of which
  have status-code-dependent consumers in the codebase (confirmed by audit).

- **OperationsService generalization (Task 3):** Adding new operation kinds extends the
  `_ensure_operation_task` routing from 2 to 4 kinds. The existing if/elif pattern scales
  to 4 without architectural change. Adding `completion_event` to the DTO is additive
  (new optional field).

- **SystemCommand dispatch seam (Task 5):** Adding `system_command()` to CommandService
  is a new method, not a refactor of existing behavior. The inline logic moves unchanged
  from routes into the handler — same code, different location. Risk is wiring errors,
  mitigated by the test specs asserting same observable behavior.

- **DELETE /sessions remote routing (Task 5):** Routing close commands to remote computers
  uses the existing transport mechanism. The `_computer` query parameter already exists on
  the route — it just needs to be read and acted on.

- **RestartAgentCommand reclassification (Task 1):** Changing from the design doc's stated
  IMMEDIATE to FIRE_AND_FORGET matches the actual current behavior (asyncio.create_task +
  "accepted" response). No consumer treats this endpoint as synchronous today.

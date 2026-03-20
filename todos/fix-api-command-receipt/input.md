# fix-api-command-receipt — Input

## Goal

Bring all mutating API endpoints into alignment with the command/receipt architecture. Synchronous fast mutations (IMMEDIATE_DATA reads and lightweight writes) are fine as-is — no receipt needed. The targets are:

1. **Fire-and-forget mutations with no tracking** → add receipt mechanism (OperationsService or event-backed)
2. **Heavy synchronous endpoints** → offload to background with receipt
3. **Endpoints bypassing CommandService entirely** → wrap in typed InternalCommand

---

## Audit findings (43 endpoints total)

### Already correct — no changes needed (10)

- POST /sessions — CreateSessionCommand
- POST /sessions/{id}/message — ProcessMessageCommand
- POST /sessions/{id}/keys — KeysCommand
- POST /sessions/{id}/voice — HandleVoiceCommand
- POST /sessions/self/file — HandleFileCommand
- POST /sessions/run — CreateSessionCommand
- POST /todos/work — OperationsService receipt
- POST /todos/integrate — OperationsService receipt
- GET /operations/{id} — receipt polling
- POST /sessions/{id}/unsubscribe — inline listener removal (appropriate)

### Synchronous fast mutations — leave as-is (no receipt needed)

- POST /agents/{agent}/status
- PATCH /settings
- POST /todos/mark-phase
- POST /todos/mark-finalize-ready
- POST /todos/set-deps
- PATCH /api/notifications/{id}/seen
- POST /api/notifications/{id}/claim
- POST /api/notifications/{id}/resolve
- PATCH /api/notifications/{id}/status
- GET/PATCH /settings

### Priority: Fire-and-forget mutations that need receipt tracking

- POST /sessions/{id}/agent-restart — dispatches async restart, returns 202 with no receipt; needs operation receipt OR agent_restart_started event
- POST /sessions/self/escalate — creates Discord thread + DB update inline, no receipt, no event; needs escalation_started event
- POST /jobs/{name}/run — BackgroundTasks wrapper, no receipt; needs operation receipt or job_started event
- DELETE /sessions/{id} — lifecycle handoff works correctly for local; needs remote routing via \_computer → session.computer_name

### Priority: Heavy synchronous endpoints to offload

- POST /todos/create — runs full creative state machine synchronously; should return receipt like /todos/work
- POST /todos/prepare — runs full prepare state machine synchronously; should return receipt like /todos/work

### Command coverage gaps (inline work that should use typed commands)

- DELETE /sessions/{id} — should use CloseSessionCommand fully (currently emits event inline)
- POST /sessions/self/result — adapter call inline; could use SystemCommand
- POST /sessions/self/widget — adapter call inline; could use SystemCommand
- POST /sessions/self/escalate — Discord + DB inline; could use SystemCommand

### Read-only endpoints — no changes (all IMMEDIATE_READ, correct)

All GET endpoints are appropriate as-is.

---

## Missing domain events to introduce

These need new events in teleclaude/core/events.py:

1. session_close_completed — confirmation that async session close finished (currently: close is fire-and-forget, no completion signal)
2. agent_restart_started — signals restart was accepted and dispatched
3. session_escalation_started — signals admin relay activation
4. job_started / job_completed / job_failed — job execution lifecycle events
5. notification_claimed / notification_resolved — notification ownership events

All new events must be domain-scoped following the existing rich eventing pattern (not simple string events).

---

## Documentation updates required

1. project/design/architecture/api-server — add command classification table (IMMEDIATE_DATA / FIRE_AND_FORGET+EVENT / RECEIPT) and which endpoints fall in each bucket
2. NEW doc: project/design/architecture/command-classification — the canonical spec for InternalCommand response_mode field, ResponseMode enum, and how API/transport/dispatch consume it
3. project/design/architecture/operation-receipts — generalize from todo-specific to describe the pattern for any heavy async operation
4. project/design/architecture/redis-transport — add section on how command response_mode determines whether the caller waits for read_response or fires-and-forgets

---

## Implementation order (suggested)

1. Write documentation first (command-classification spec, update api-server and operation-receipts docs)
2. Add ResponseMode enum + field to InternalCommand base class
3. Migrate \_dispatch_command() from isinstance chains to metadata-driven dispatch
4. Wrap DELETE /sessions/{id} fully in CloseSessionCommand with remote routing via session.computer_name
5. Add receipts to /todos/create and /todos/prepare (offload to OperationsService)
6. Add receipts to /sessions/{id}/agent-restart
7. Introduce missing domain events
8. Update /jobs/{name}/run with receipt or event

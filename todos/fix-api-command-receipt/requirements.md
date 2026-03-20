# Requirements: fix-api-command-receipt

## Goal

Bring all mutating API endpoints into alignment with the command-classification
design. Every mutation must declare its response mode (IMMEDIATE, FIRE_AND_FORGET,
or RECEIPT) on the command object, and the API/dispatch layers must derive behavior
from that declaration — not from isinstance chains or hardcoded status codes.

## Scope

### In scope

- Implementing the ResponseMode mechanism on the command base type and all subclasses
- Refactoring command dispatch to be metadata-driven (read response_mode, not isinstance)
- Adding receipt-backed operation handling for heavy synchronous endpoints (todo create, todo prepare)
- Adding domain event emission for fire-and-forget mutations that currently lack completion signals
- Wrapping inline adapter/DB work in typed commands where the input audit identifies command coverage gaps
- Introducing missing domain events for session close completion, agent restart, escalation, and job lifecycle
- Updating the operation receipts architecture to support operation kinds beyond todo-specific ones

### Out of scope

- Read-only (GET) endpoints — already correct per audit
- Synchronous fast mutations identified as "leave as-is" in the audit (agent status, settings, mark-phase, notification CRUD) — no receipt needed
- WebSocket/SSE push infrastructure changes — the event bus already supports push; this work adds events to it, not new transport

## Functional Requirements

### FR-1: Response mode declaration on commands

Every command subclass must declare its response mode as a field on the command
object. The base command type must carry both the response mode and a completion
event identifier. [inferred] Commands with FIRE_AND_FORGET mode must declare a
non-null completion event. This invariant must be enforced at construction time,
not at dispatch time. [inferred: construction-time enforcement preferred over dispatch-time
to fail fast]

**Success criteria:**
- All existing command subclasses declare their response mode
- FIRE_AND_FORGET commands without a completion event fail at instantiation
- No command defaults to a mode that contradicts the command-classification design doc [inferred]

### FR-2: Metadata-driven command dispatch

The command dispatcher must read the command's response mode to determine execution
behavior (sync return vs. fire-and-forget vs. receipt) instead of using type-based
isinstance chains.

**Success criteria:**
- Dispatch logic branches on response_mode, not on command class identity
- Adding a new command subclass requires no changes to the dispatcher — mode is
  inherited from the command declaration
- Existing behavior for all currently-correct endpoints is preserved (no regressions)

### FR-3: Receipt-backed operation handling for heavy endpoints

The todo create and todo prepare endpoints currently run full state machines
synchronously. They must be migrated to the receipt-backed operation pattern
(persist operation row, return receipt immediately, execute in background,
emit completion event on terminal transition).

**Success criteria:**
- POST /todos/create returns an operation receipt (202) instead of blocking
- POST /todos/prepare returns an operation receipt (202) instead of blocking
- Both operations support polling via the existing operations endpoint
- Both operations emit a completion event on terminal transition
- Deduplication via client_request_id works for both new operation kinds [inferred]
- Stale-on-restart marking applies to these operations [inferred]

### FR-4: Domain event emission for fire-and-forget mutations

Fire-and-forget mutations must emit domain events that signal completion or
acceptance. The following endpoints currently lack completion signals:

1. Agent restart — must emit an event when restart is dispatched [inferred: "dispatched" rather than "completed" since restart is handed off to the agent runtime]
2. Session escalation — must emit an event when escalation is initiated
3. Job execution — must emit lifecycle events (started, completed, failed)
4. Session close — must emit a completion event when close processing finishes
5. Notification claim — must emit an event when a notification is claimed [inferred: from input.md event list]
6. Notification resolve — must emit an event when a notification is resolved [inferred: from input.md event list]

All new events must follow the existing domain event pattern (typed payload
dataclasses, emitted via the event bus).

**Success criteria:**
- Each listed endpoint emits its declared completion event
- Events carry enough context for consumers to correlate (session ID, job name, etc.)
- Events follow the existing payload pattern (typed dataclasses, not ad-hoc dicts)
- The 202 response for fire-and-forget endpoints includes the completion_event name

### FR-5: Typed command wrapping for inline mutations

Endpoints that currently perform adapter or DB mutations inline without going
through a typed command must be wrapped in the command system. The input audit
identifies: session result delivery, widget rendering, and session escalation.

Additionally, `DELETE /sessions/{id}` must route through `CloseSessionCommand`
via the command system instead of emitting events inline. When
`session.computer_name` differs from the local computer, the command must be
forwarded via the existing remote transport mechanism rather than handled locally.
[inferred: remote-routing completes the close-session command coverage gap
identified in the input audit]

**Success criteria:**
- Identified inline mutations flow through typed commands
- The command type and response mode are declared, not implicit
- `DELETE /sessions/{id}` routes through the command system with remote-routing support
- No adapter-specific logic is introduced into the command layer [inferred: per boundary purity principle]

### FR-6: Documentation deliverables

The following architecture documents must be updated to reflect the implemented
changes. Documentation must describe the actual implemented state, not the
pre-implementation design.

1. Command classification design doc — correct any classification errors,
   add the full endpoint-to-mode mapping table, update the base command
   fields specification to match the implemented constructor pattern
2. Operation receipts design doc — generalize from todo-specific to describe
   the pattern for any heavy async operation, add all operation kinds to the
   inventory
3. API server design doc — add command classification table showing which
   endpoints fall in each response mode bucket
4. Redis transport design doc — add section on how the command response mode
   determines caller behavior (await response vs. fire-and-forget)

[inferred: four documentation deliverables explicitly listed in input.md]

**Success criteria:**
- All four documents exist and reflect the implemented architecture
- Classification errors in existing docs are corrected
- Operation receipts doc covers all operation kinds, not just todo-specific ones
- Redis transport doc explains response-mode-driven caller behavior

## Acceptance Criteria

- [ ] All mutating endpoints map to one of the three response modes per the command-classification design
- [ ] No isinstance chains remain in command dispatch for mode selection
- [ ] /todos/create and /todos/prepare return receipts and execute in background
- [ ] Fire-and-forget endpoints return 202 with completion_event in the response body
- [ ] All new domain events are typed payload dataclasses following existing patterns
- [ ] Receipt polling via /operations/{id} works for all receipt-backed operations
- [ ] Pre-commit hooks pass (lint, typecheck, tests) [inferred]
- [ ] Endpoints the input marks "already correct" keep their current response codes and response shapes
- [ ] Operation deduplication and stale-on-restart behavior extend to new operation kinds [inferred]
- [ ] DELETE /sessions/{id} routes through CloseSessionCommand with remote-routing for non-local sessions
- [ ] Notification claim and resolve endpoints emit typed domain events
- [ ] Four architecture documents updated to reflect implemented state (command-classification, operation-receipts, api-server, redis-transport)

## Dependency / Prerequisites

- **web-tui-parity** — roadmap dependency (must be delivered first per `roadmap.yaml`)
- **command-classification design doc** — already exists and describes the target architecture; implementation must conform to it
- **operation-receipts design doc** — already exists; the receipt pattern must be generalized, not reimplemented

## Constraints

- The ResponseMode mechanism described in the command-classification design doc is the
  target architecture. Implementation must conform to it — do not invent an alternative.
- Existing correct endpoints (the 10 "already correct" and the fast mutations) must not
  change behavior.
- The operation receipts pattern (persist-before-execute, atomic terminal transition,
  stale-on-restart) applies to all new receipt-backed operations.
- New domain events must be domain-scoped (not transport-scoped) following the existing
  rich eventing pattern.

## Risks

- **Regression surface:** Refactoring dispatch touches all command processing. Mitigation:
  existing test coverage for command handling, plus new tests for mode-driven dispatch.
- **OperationsService generalization:** Extending beyond todo-specific operations may
  require changes to deduplication keys and operation kind registry. Mitigation: the
  existing pattern is already parametric on kind — extension should be mechanical.
- **Scope creep from command wrapping (FR-5):** Wrapping inline mutations in typed commands
  could surface design questions about command granularity. Mitigation: keep wrapping
  mechanical — match existing SystemCommand pattern where appropriate.

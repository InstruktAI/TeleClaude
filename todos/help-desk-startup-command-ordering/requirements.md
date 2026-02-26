# Requirements: help-desk-startup-command-ordering

## Goal

Guarantee deterministic ordering between help-desk session bootstrap
(auto-start command) and first inbound customer message so the first turn is
always processed as a valid agent conversation turn.

## Why

Current behavior can produce a session with no answer even though tmux exists and
auto-command is queued. The failure is user-visible and silent unless operators
inspect low-level logs/pane state.

## In Scope

1. Startup ordering contract between bootstrap and `process_message`.
2. Lifecycle transition timing (`initializing` to `active`) for new sessions.
3. Safe first-message gating during startup.
4. Observability for deferred message handling and startup completion.
5. Regression coverage for the identified race.

## Out of Scope

1. Multi-phase lifecycle redesign beyond this ordering fix.
2. Changes to non-session startup systems.
3. Help-desk product UX redesign.

## Functional Requirements

### FR1: Startup Ordering Invariant

1. For sessions created with `auto_command`, `process_message` MUST NOT inject
   user text into tmux while session lifecycle is `initializing`.
2. `initializing` MUST remain in effect until bootstrap completes tmux setup and
   auto-command dispatch attempt.

### FR2: First-Message Safety

1. First inbound message MUST be processed only after startup gate opens.
2. The message MUST remain a standalone input payload (no concatenation with
   startup command line).

### FR3: Explicit Failure Behavior

1. If startup readiness does not resolve within a bounded timeout, system MUST
   emit a user-visible error path and skip tmux injection for that message.
2. Timeout/failure MUST be logged with session identifier and gate state.

### FR4: Compatibility

1. Sessions without `auto_command` MUST keep existing behavior.
2. Existing headless adoption behavior MUST remain unchanged.

### FR5: Observability

1. Logs MUST indicate when a message is gated on `initializing`.
2. Logs MUST indicate when gating resolves and message dispatch continues.
3. Logs MUST indicate timeout/failure branch activation.

## Verification Requirements

1. Unit test: bootstrap marks session `active` only after auto-command dispatch
   attempt completes.
2. Unit test: `process_message` waits through `initializing` and dispatches once
   session is ready.
3. Unit test: timeout path emits explicit error and does not call tmux send.
4. Regression check: no contamination of startup command by first inbound text.

## Success Criteria

- [ ] Reproduction scenario no longer produces contaminated startup command.
- [ ] First help-desk message receives normal agent response path.
- [ ] Logs clearly show gate wait/resume (or timeout) for startup ordering.
- [ ] Targeted test suite covers success and timeout branches.

## Constraints

- Keep change atomic and merge-safe.
- Preserve adapter/core boundary discipline.
- Use existing command service and lifecycle primitives where possible.

## Risks

1. Overly strict gate timeout can delay or drop legitimate first messages.
2. Incorrect lifecycle transition ordering can strand sessions in `initializing`.
3. New wait logic can introduce deadlock-like behavior if not bounded.

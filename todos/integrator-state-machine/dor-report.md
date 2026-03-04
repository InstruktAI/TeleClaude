# DOR Report: integrator-state-machine

## Assessment

### 1. Intent & Success

- Problem statement clear: replace prose-based `/next-integrate` command with deterministic
  state machine that returns structured instruction blocks at agent decision points
- Outcome explicit: `telec todo integrate` called repeatedly advances through the full
  integration lifecycle
- 12 concrete, testable success criteria in requirements.md

### 2. Scope & Size

- Core state machine + CLI + API + command update + lifecycle events + tests
- Follows established `next_work()` pattern — wiring, not greenfield
- All primitives delivered and tested (queue, lease, readiness, clearance, follow-up)
- **Note:** If context exhaustion is a risk during build, Phase 2 (lifecycle events)
  could be deferred to a follow-up todo without blocking the core functionality

### 3. Verification

- Unit tests for checkpoint, phase handlers, idempotency, crash recovery
- Integration test for full candidate lifecycle
- CLI and API smoke tests in demo.md
- `make test` and `make lint` as final gates

### 4. Approach Known

- `next_work()` in `core.py` is the direct template — same async function signature,
  same plain-text instruction block output, same `format_tool_call()` formatting
- Checkpoint follows `IntegrationQueue` atomic write pattern
- Git operations (fetch, merge --squash, push) are well-understood
- Decision points modeled on the actor model in input.md

### 5. Research Complete

- No third-party dependencies introduced
- All primitives are internal, delivered, and tested
- Prior art (`next_work()`) thoroughly analyzed
- Existing `/next-integrate` command spec documented current prose approach
- Integration bridge event helpers mapped to new lifecycle events

### 6. Dependencies & Preconditions

- All prerequisite primitives delivered: `IntegrationQueue`, `IntegrationLeaseStore`,
  `ReadinessProjection`, `MainBranchClearanceProbe`, `BlockedFollowUpStore`,
  `IntegratorCutoverControls`, `integration_bridge.py`
- No external system dependencies
- No new configuration required (checkpoint path follows existing convention:
  `~/.teleclaude/integration/checkpoint.json`)

### 7. Integration Safety

- Additive: new module (`state_machine.py`), new route, new CLI command
- `/next-integrate` command updated but same integration flow (state machine replaces
  prose, not behavior)
- No changes to existing primitives
- Rollback: revert command spec to prose version, remove new module

### 8. Tooling Impact

- New CLI command `telec todo integrate` added to CLI surface in `telec.py`
- No scaffolding procedure changes needed

## Assumptions

- The state machine replaces `IntegratorShadowRuntime.queue_drain()` as the agent-facing
  entry point. The runtime's primitives (lease, clearance) are reused directly but
  `queue_drain()` is no longer called by the agent loop.
- Checkpoint file is per-integration-run at `~/.teleclaude/integration/checkpoint.json`,
  tracking the current candidate and resetting between candidates within the same drain.
- The `/next-integrate` command's agent loop calls `telec todo integrate` repeatedly;
  behavioral guidance (commit message quality, conflict resolution approach) remains
  as agent-turn instructions in the command spec.
- Lifecycle events are additions alongside existing bridge events (`emit_deployment_*`),
  not replacements. The bridge helpers remain for backward compatibility; the state machine
  emits lifecycle events directly.
- `make restart` runs per candidate during cleanup (code changes may affect daemon behavior),
  matching the existing `/next-integrate` spec.

## Open Questions

1. **Event deduplication:** The bridge already emits `emit_deployment_completed` and
   `emit_deployment_failed`. The new lifecycle events (`integration.candidate.delivered`,
   `integration.candidate.blocked`) overlap semantically. Should the state machine emit
   only lifecycle events and retire the bridge helpers, or emit both for backward
   compatibility? (Inferred: emit lifecycle events from state machine; keep bridge helpers
   available but don't double-emit for the same state transition.)

## Draft Verdict

**Status:** needs_work (draft phase — gate has not run)
**Score:** 0 (pre-gate)

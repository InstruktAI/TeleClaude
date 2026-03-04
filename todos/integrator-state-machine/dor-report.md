# DOR Report: integrator-state-machine

## Gate Verdict: PASS (score 8/10)

All eight DOR gates satisfied. Two minor clarifications noted for builder awareness;
neither blocks readiness.

---

## Gate Assessment

### 1. Intent & Success — PASS

- Problem statement explicit: replace prose `/next-integrate` with a deterministic
  Python state machine returning structured instruction blocks at decision points.
- Outcome concrete: `telec todo integrate` called repeatedly advances through the
  full integration lifecycle for one candidate, then the next.
- 12 testable success criteria in requirements.md — each maps to observable behavior.
- The actor model in input.md clearly separates script turns (deterministic) from
  agent turns (intelligent). Requirements and plan faithfully preserve this separation.

### 2. Scope & Size — PASS

- Six implementation phases; bulk is Phase 1 (state machine core) and Phase 5 (tests).
- Not greenfield — wires existing, tested primitives through a new coordination layer.
- The `next_work()` function at `core.py:2656` is the direct template; the builder has
  a concrete pattern to follow.
- Contingency: Phase 2 (lifecycle events) can be deferred if context becomes tight.
  This is explicitly noted in the draft and is a sound escape hatch.

### 3. Verification — PASS

- Unit tests specified: checkpoint read/write/recovery, each phase handler, idempotency,
  crash recovery.
- Integration test: full candidate lifecycle (merge → commit → push → cleanup).
- Scenario coverage: queue drain, blocked candidate, clearance wait, push rejection.
- Demo.md provides CLI and API smoke tests.
- Final gates: `make test`, `make lint`.

### 4. Approach Known — PASS

- `next_work()` at `core.py:2656` — async function returning plain text instruction
  blocks via `format_tool_call()` at `core.py:273`. Direct template.
- Atomic checkpoint: `IntegrationQueue` at `queue.py:77` uses the same temp file +
  `os.replace` pattern specified for the checkpoint.
- Git operations (fetch, merge --squash, push) are standard and well-understood.
- All phase handlers follow a consistent pattern: execute deterministic block →
  update checkpoint → return instruction block or continue.

### 5. Research Complete — PASS

- No third-party dependencies introduced.
- All eight primitives confirmed in codebase:
  - `IntegrationQueue` — `queue.py:77`
  - `IntegrationLeaseStore` — `lease.py:67`
  - `ReadinessProjection` — `readiness_projection.py:62`
  - `MainBranchClearanceProbe` — `runtime.py:131`
  - `BlockedFollowUpStore` — `blocked_followup.py:57`
  - `IntegratorCutoverControls` — `authorization.py:14`
  - `IntegratorShadowRuntime` — `runtime.py:205`
  - `integration_bridge.py` — event emission helpers (lines 51, 80, 107)
- Existing `/next-integrate` command spec at `agents/commands/next-integrate.md`
  documents current prose approach.
- `deliver_to_delivered()` at `core.py:1632` — Python-level delivery function available.

### 6. Dependencies & Preconditions — PASS

- All prerequisite primitives delivered and tested.
- No external system dependencies.
- No new configuration required — checkpoint path follows existing convention.
- Template code (`todo_work` route at `todo_routes.py:65`, `handle_todo_work` at
  `tool_commands.py:771`) confirmed as direct wiring models.
- No new config keys needed; no wizard exposure required.

### 7. Integration Safety — PASS

- Additive: new module (`state_machine.py`), new API route, new CLI command.
- The `/next-integrate` command is updated (same flow, state machine replaces prose).
- No changes to existing primitives — reuse only.
- Rollback: revert command spec, remove new module. Clean and low-risk.

### 8. Tooling Impact — PASS

- New CLI command `telec todo integrate [<slug>]` added to `CLI_SURFACE` in `telec.py`.
- No scaffolding procedure changes needed.
- Gate automatically satisfied.

---

## Plan-to-Requirement Fidelity

Every implementation plan task traces to a requirement. Key fidelity checks:

- Requirements: "follow `next_work()` pattern" → Plan: Tasks 1.2 explicitly mirrors
  the async function signature and `format_tool_call()` output.
- Requirements: "checkpoint must be atomic" → Plan: Task 1.1 specifies temp file +
  `os.replace` matching `IntegrationQueue` pattern.
- Requirements: "state machine must not perform git operations requiring agent
  intelligence" → Plan: Task 1.3 returns decision points at merge composition,
  conflict resolution, and push rejection — never attempts these itself.
- Requirements: "reuse existing primitives" → Plan: all phase handlers reference
  specific primitives by class name.

No plan task contradicts a requirement.

---

## Builder Notes (non-blocking)

1. **Cutover controls placement.** `IntegratorCutoverControls` (`authorization.py:14`)
   is listed as a reuse primitive in requirements but not explicitly placed in the state
   machine flow. The builder should wire `resolve_cutover_mode()` at the entry point
   (before lease acquisition in Task 1.2). The existing `/next-integrate` command
   already uses it via `IntegratorShadowRuntime` with `shadow_mode=False`.

2. **Python-level APIs for delivery bookkeeping.** Task 1.3 (DELIVERY_BOOKKEEPING)
   references `telec roadmap deliver {slug}` as a CLI call. The state machine is Python;
   use `deliver_to_delivered()` at `core.py:1632` directly. Similarly, `telec todo demo
   create` should call its underlying Python function rather than shelling out.

Both are implementation-level details the builder will naturally resolve.

---

## Assumptions (from draft, validated)

- The state machine replaces `IntegratorShadowRuntime.queue_drain()` as the agent-facing
  entry point. The runtime's primitives are reused; `queue_drain()` is no longer called.
  **Validated:** `queue_drain` exists in runtime.py; the plan correctly supersedes it.
- Checkpoint file at `~/.teleclaude/integration/checkpoint.json` — consistent with
  existing integration data paths. **Validated.**
- Lifecycle events are additions alongside existing bridge events, not replacements.
  Bridge helpers remain for backward compatibility. **Validated:** bridge events
  (`emit_deployment_started/completed/failed`) emit through the event pipeline;
  new lifecycle events run in parallel without duplication.
- `make restart` per candidate during cleanup matches existing spec. **Validated.**

## Open Questions (resolved)

1. **Event deduplication** (from draft): Inferred resolution is sound — state machine
   emits lifecycle events; bridge helpers remain available but are not double-emitted
   for the same transition. The builder should ensure the bridge calls in the current
   `/next-integrate` prose flow are not inherited into the state machine (the state
   machine has its own lifecycle events).

---

## Verdict

**Score:** 8/10
**Status:** pass
**Blockers:** none

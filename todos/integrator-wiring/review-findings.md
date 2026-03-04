# Review Findings: integrator-wiring

**Reviewer:** Claude (automated)
**Review round:** 1
**Scope:** 17 files changed (+1285 / -505 lines), 12 commits on `integrator-wiring` branch
**Verdict:** APPROVE

---

## Critical

_(None)_

## Important

### I-1: Cartridge docstring claims readiness-projection feeding, but code does not feed it

**Location:** `teleclaude_events/cartridges/integration_trigger.py:1-6, 32-39`
**Principle:** Documentation accuracy / Failure Modes (comment over-trust)

The module docstring says "feeds integration events to readiness projection" and the
class docstring says "extracts (slug, branch, sha) and feeds to the readiness
projection. When a candidate goes READY, invokes the spawn callback." The actual
`process()` method does neither — it only checks for `deployment.started` and calls
the spawn callback directly. No `ReadinessProjection` or `IntegrationEventService`
is referenced.

This is architecturally defensible (deployment.started is only emitted after all
readiness prerequisites are met), but the docstrings describe a more sophisticated
flow than what exists. Future maintainers may rely on the described behavior.

**Remediation:** Update module and class docstrings to describe the actual behavior:
the cartridge watches for deployment.started events and triggers the spawn callback
directly. The readiness projection is used inside the integrator runtime, not in the
cartridge.

### I-2: `spawn_integrator_session` returns None for both "already running" and "spawn failed"

**Location:** `teleclaude/core/integration_bridge.py:165-170, 185-189`
**Principle:** Fail Fast / Encapsulation

The function returns `None` for three distinct situations:
1. Integrator already running (line 186) — expected, candidate is queued
2. Could not check for running sessions (line 189) — ambiguous
3. Spawn failed with any exception (line 170) — error

The caller (trigger cartridge at line 75-79) cannot distinguish between these. The
broad `except Exception` at the outer level also masks unexpected errors. Combined
with the cartridge's own `except Exception` (line 78-79), this creates a two-layer
catch-and-continue chain where spawn failures are buried in warning-level logs.

**Remediation:** Consider returning a typed result (e.g., `SpawnOutcome` enum with
`spawned`, `already_running`, `check_failed`, `spawn_failed`) so the cartridge can
log at appropriate severity levels. At minimum, the "already running" path should
return a distinguishable value from error paths.

### I-3: No test coverage for `spawn_integrator_session` / `_spawn_integrator_sync`

**Location:** `teleclaude/core/integration_bridge.py:149-222`
**Principle:** Testing policy

This function is the critical runtime bridge that spawns the singleton integrator.
It contains subprocess calls, environment manipulation, string-based detection of
running integrators (`"integrator" in list_result.stdout.lower()`), and specific
argument construction for `telec sessions start`. None of this is tested.

The string-based detection is particularly fragile — it would match any session
whose title or output contains "integrator" regardless of context.

**Remediation:** Add unit tests with subprocess mocking to cover: (1) already-running
detection, (2) successful spawn, (3) spawn failure, (4) timeout handling. The
substring match should also be tightened (e.g., match on a session title prefix).

### I-4: Dead `DUPLICATE` variant in `IngestionStatus`

**Location:** `teleclaude/core/integration/service.py:28`
**Principle:** YAGNI / Dead code

`IngestionStatus = Literal["APPENDED", "DUPLICATE", "REJECTED"]` includes `DUPLICATE`
but no code path produces it after file store removal. The file store's dedup logic
was the only source of DUPLICATE results. The type is exported from `__init__.py`.

**Remediation:** Remove `DUPLICATE` from the Literal type, or add a comment noting
it's retained for external consumer compatibility.

## Suggestions

### S-1: POST_COMPLETION deployment.started emission fallback could leave candidate stuck

**Location:** `teleclaude/core/next_machine/core.py:241-246` (POST_COMPLETION text)

The inline Python emission has `|| echo "WARNING: deployment.started emission failed
(non-blocking)"`. If emission fails, the finalize flow continues (lock released,
next_call invoked) but no integrator triggers. The candidate would be stuck —
finalized but never integrated.

This is mitigated by: (1) the agent seeing the WARNING and escalating, (2) Redis
Streams durability, (3) the integrator can be manually spawned. But it's worth
noting as a potential operational gap.

### S-2: `_SpawnResult` TypedDict placement

**Location:** `teleclaude/core/integration_bridge.py:140-142`

The TypedDict is defined between section separator comments in an awkward position —
between the end of the emission helpers section and the spawn section header. Minor
readability issue.

---

## Requirements Tracing

| Requirement | Status | Evidence |
|---|---|---|
| FR1: Event schemas | Met | 4 schemas in `software_development.py:112-154`, lifecycle declarations match spec |
| FR2: Event emission | Met | Bridge in `integration_bridge.py`, wired at `core.py:3097` (review.approved) and POST_COMPLETION (deployment.started) |
| FR3: Integrator trigger | Met | Cartridge in `integration_trigger.py`, registered in `daemon.py:1730-1731` |
| FR4: POST_COMPLETION replacement | Met | Old 12-step merge/push removed, replaced with event emission + handoff |
| FR5: Integrator session | Met | Command artifact `next-integrate.md`, runtime tested via queue drain tests |
| FR6: Cutover activation | Met | `daemon.py:1666` sets `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED=1`, spawn sets parity evidence |
| FR7: File store replaced | Met | `service.py` no longer imports/uses `IntegrationEventStore`, factory renamed to `create()` |
| FR8: Sync removal | Met | `sync_slug_todo_from_worktree_to_main` and `sync_slug_todo_from_main_to_worktree` fully removed, `is_bug_todo` calls corrected to use main repo path |

## Paradigm-Fit Assessment

1. **Data flow**: Events flow through the established event platform pipeline
   (`EventProducer` → Redis Streams → `EventProcessor` → cartridge chain). The
   bridge uses `emit_event()` — the canonical emission interface. No bypasses.
2. **Component reuse**: The trigger cartridge follows the cartridge interface
   (`process(event, context) -> EventEnvelope | None`). The service factory
   method follows the established classmethod pattern.
3. **Pattern consistency**: Logging uses the project's structured logger. Subprocess
   spawning in the bridge follows the same patterns as other daemon-to-session
   interactions. POST_COMPLETION text follows the established agent instruction format.

## Demo Assessment

9 executable blocks covering: schema registration, cartridge instantiation, bridge
imports, sync removal verification, file store decoupling, command artifact existence,
cutover env vars, phantom directory cleanup, and integration test execution. All
blocks exercise real implementation behavior. Demo quality is adequate.

## Test Coverage Assessment

- **Well covered**: Event schemas, bridge emission (4 functions), trigger cartridge
  (fire + pass-through), service without file store, queue drain FIFO, self-end on
  empty, would_block outcome, notification lifecycle, bidirectional sync removal,
  POST_COMPLETION regression.
- **Gap**: `spawn_integrator_session` / `_spawn_integrator_sync` has zero test
  coverage (flagged as I-3).
- **Existing tests updated correctly**: Sync tests removed, replay tests adapted to
  pipeline-fed model, POST_COMPLETION assertions updated.

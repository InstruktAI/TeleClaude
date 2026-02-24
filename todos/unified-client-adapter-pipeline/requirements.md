# Requirements - unified-client-adapter-pipeline

## Problem

Client update paths are inconsistent:

- Some adapters consume standardized adapter fanout.
- Web/TUI paths include direct API/event channels that bypass parts of the adapter pipeline.

This creates architectural drift, inconsistent behavior across surfaces, and harder debugging/observability.

## Goal

Unify all human-facing clients behind one adapter pipeline and one realtime stream contract by aligning Web and TUI with the existing adapter-driven routing model already used by Telegram and Discord.

## Dependency

- Must run after `transcript-first-output-and-hook-backpressure`.

## Canonical Contract Baseline

- Use the target streaming shape from `docs/project/design/architecture/agent-activity-streaming-target.md`.
- Keep routing semantics compatible with `docs/project/spec/session-output-routing.md`.
- Preserve adapter boundary rules in `docs/project/policy/adapter-boundaries.md`.

## In Scope

- Define canonical outbound update contract for all clients.
- Add/align Web and TUI adapter behavior on that contract.
- Remove direct bypass paths that skip adapter fanout contract.
- Keep snapshot/history API support while unifying realtime delivery semantics.
- Normalize client input mapping into the same command ingress pipeline.
- Limit Telegram/Discord changes to compatibility and parity validation (no new UX features in this todo).

## Out of Scope

- New front-end features unrelated to transport harmonization.
- Rewriting the whole API server.
- Provider-specific model behavior changes.

## Functional Requirements

### R1. Unified outbound contract

- Define one normalized realtime payload schema used by all clients.
- Contract must cover:
  - session output deltas
  - session/activity status updates
  - control notifications (input required, stop events, etc.)
- Canonical activity event names for this todo are:
  - `user_prompt_submit`
  - `agent_output_update`
  - `agent_output_stop`
- Delivery routing for output progression must remain intent-driven (`message_intent` + `delivery_scope`), not adapter-specific branching.

### R2. Adapter parity for Web and TUI

- Web and TUI must consume the same normalized update stream shape.
- No client may rely on private bypass-only semantics for core output progression.
- Web protocol translation (for example SSE framing) must happen at the adapter edge, not via a separate core-output bypass path.

### R3. Unified ingress mapping

- Input from Web/TUI/Telegram/Discord maps through the same command pipeline semantics.
- Actor identity and provenance mapping must remain consistent across clients.

### R4. Channel/provisioning consistency

- Provisioning/route decisions must be centralized in adapter/channel orchestration.
- Client-specific branch logic should be minimal and presentation-focused.

### R5. Observability

- Add tracing/metrics that allow comparing delivery consistency across client adapters.
- Errors must identify adapter lane, session, and contract event type.

## Non-Functional Requirements

- Preserve backward compatibility during migration (shadow mode/cutover).
- No regressions in delivery correctness.
- Keep latency within current operational expectations.

## Acceptance Criteria

1. Web and TUI realtime updates are generated from the same canonical adapter output contract.
2. No direct client bypass path remains for core output progression.
3. Equivalent session updates are visible across Web/TUI/Telegram/Discord for the same session state.
4. Input handling semantics are consistent across clients (including provenance metadata).
5. Contract tests validate payload shape and required fields for all client lanes.

## Risks

- Migration overlap can temporarily duplicate updates if cutover is partial.
- Client assumptions tied to legacy payloads may need compatibility shims during rollout.

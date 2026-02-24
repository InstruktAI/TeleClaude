# Requirements: ucap-canonical-contract

## Problem

Realtime client updates currently mix multiple payload shapes and translation points.
Web/TUI unification work needs a single canonical outbound contract so downstream adapter
alignment can remove bypass behavior without schema drift.

## Goal

Define and adopt a canonical outbound realtime activity contract, plus shared
serializer/validation utilities, so all client adapters can consume one normalized
event model in later UCAP phases.

## Dependency

- Must run after `transcript-first-output-and-hook-backpressure`.

## In Scope

- Define canonical outbound activity event types and required fields.
- Define mapping between activity events and routing semantics (`message_intent`,
  `delivery_scope`) per session output routing policy.
- Add shared serializer/validation utilities used by output producers.
- Introduce compatibility translation so existing consumers remain functional during
  phased migration.
- Add tests and documentation for the contract.

## Out of Scope

- Full Web adapter cutover/removal of all bypass paths (handled by `ucap-web-adapter-alignment`).
- Full TUI adapter cutover/removal of all bypass paths (handled by `ucap-tui-adapter-alignment`).
- Ingress/provisioning harmonization changes (handled by `ucap-ingress-provisioning-harmonization`).
- UI redesign or adapter-specific presentation changes.

## Functional Requirements

### R1. Canonical outbound activity vocabulary

- Canonical activity events for this phase are:
  - `user_prompt_submit`
  - `agent_output_update`
  - `agent_output_stop`
- Contract includes stable routing metadata compatible with
  `docs/project/spec/session-output-routing.md`.

### R2. Canonical payload schema

- Canonical payload schema defines required fields, optional fields, and allowed values.
- Required identity/routing fields must include at least:
  - session identity
  - event type
  - event timestamp
  - routing intent/scope metadata for fan-out decisions
- Event-specific payload details must be explicit and typed.

### R3. Shared serializer and validation utilities

- A shared utility layer serializes outbound activity updates into canonical schema.
- Validation failures are explicit (log + metric/counter) and must not crash output flow.
- Producers must use the shared utilities rather than hand-crafting adapter payloads.

### R4. Producer integration boundary

- Output-producing paths (poller/coordinator activity emission) must route through one
  canonical serialization/validation boundary before fan-out.
- Core logic must not emit adapter-specific transport envelopes.

### R5. Compatibility bridge for existing consumers

- Existing consumers of current activity payloads remain supported during this phase.
- Compatibility translation is derived from canonical contract (single source), not
  duplicate independent payload shaping.

### R6. Documentation updates

- Architecture/spec docs are updated with canonical schema, allowed values, and examples.
- Contract ownership and backward-compatibility notes are explicit.

## Non-Functional Requirements

- No new third-party dependencies are introduced.
- Contract serialization/validation overhead is bounded and does not materially affect
  output cadence.
- Adapter boundary policy remains enforced (no adapter-specific types in core).

## Success Criteria

### SC-1: Canonical contract is explicit and versioned in project docs

Verification:

- Docs include canonical activity event vocabulary and field-level contract with examples.

### SC-2: Shared serializer/validator exists and is used by producers

Verification:

- Relevant output producer paths call shared utilities.
- No duplicate ad-hoc contract shaping remains in those producer paths.

### SC-3: Validation failure behavior is deterministic

Verification:

- Invalid payload tests confirm explicit failure reporting and non-crashing behavior.

### SC-4: Compatibility with existing activity consumers is preserved

Verification:

- Current API/TUI activity event consumers continue to pass regression tests.

### SC-5: Routing semantics are encoded in canonical event data

Verification:

- Contract tests assert message intent/scope mapping for output and control event classes.

### SC-6: Contract test coverage exists at unit level

Verification:

- Unit tests cover serializer success/failure, field requirements, and event-type mapping.

### SC-7: No new third-party research dependency is introduced

Verification:

- Implementation uses existing repository/runtime tooling only.

## Constraints

1. Must remain compatible with `docs/project/design/architecture/agent-activity-streaming-target.md`.
2. Must preserve routing semantics from `docs/project/spec/session-output-routing.md`.
3. Must preserve adapter/core separation from `docs/project/policy/adapter-boundaries.md`.

## Risks

- Ambiguity between legacy `agent_activity` payload shape and new canonical contract can
  cause dual-shape drift if compatibility mapping is not centralized.
- If contract scope grows beyond this phase, downstream alignment todos may lose atomicity.

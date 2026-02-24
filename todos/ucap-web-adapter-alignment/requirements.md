# Requirements - ucap-web-adapter-alignment

## Problem

Web output currently includes bypass semantics outside the canonical adapter contract, which creates inconsistent behavior and observability drift.

## Goal

Align Web realtime delivery to canonical adapter-driven outbound events while preserving Web protocol translation at the edge.

## Dependency

- Must run after `ucap-truthful-session-status`.

## Preconditions

- `ucap-truthful-session-status` contract surfaces are available to the Web lane.
- Existing Web streaming/runtime surfaces are available in local test harnesses via mocks/stubs.
- No new third-party SDK adoption is required; existing AI SDK UI stream integration is reused.

## In Scope

- Web adapter lane consumption of canonical outbound events.
- Removal of direct Web bypass for core output progression.
- Edge-only protocol translation (e.g., SSE formatting).
- Web regression coverage for canonical event flow.

## Out of Scope

- TUI lane migration.
- Ingress/provisioning harmonization.
- Global cutover and parity scoring.

## Functional Requirements

### R1. Canonical contract consumption

- Web realtime pipeline must consume canonical outbound event schema.

### R2. Bypass removal

- No direct Web-only core output bypass path remains.

### R3. Edge translation boundary

- Web protocol formatting occurs at adapter edge only, not in core output generation.

### R4. Observability parity for Web lane

- Web lane logs/metrics identify adapter lane and canonical event type.

## Acceptance Criteria

1. Web realtime updates originate from canonical adapter event stream.
2. Direct Web bypass path for core output progression is removed.
3. Edge translation remains isolated to Web adapter/presentation boundary.
4. Web-focused tests validate canonical payload path and regressions.

## Research References

- `docs/third-party/ai-sdk/ui-message-stream-status-parts.md`

## Risks

- Partial cutover can produce temporary duplicate Web updates.
- Edge translation leakage into core layer can reintroduce coupling.

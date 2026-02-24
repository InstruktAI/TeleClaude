# Requirements - ucap-tui-adapter-alignment

## Problem

TUI output handling can diverge from adapter contract semantics when bypass paths are used, creating inconsistent client behavior.

## Goal

Align TUI realtime delivery with canonical adapter outbound events while keeping presentation-only logic local to TUI components.

## Dependency

- Must run after `ucap-truthful-session-status`.

## In Scope

- TUI lane consumption of canonical outbound events.
- Removal of TUI bypass behavior for core output progression.
- Preservation of TUI-only rendering concerns in TUI layer.
- TUI regression coverage for canonical event flow.

## Out of Scope

- Web migration.
- Ingress/provisioning harmonization.
- Global cutover and cross-adapter parity scoring.

## Functional Requirements

### R1. Canonical contract consumption

- TUI realtime updates must be sourced from canonical outbound event schema.

### R2. Bypass removal

- No TUI-specific core output bypass path remains.

### R3. Presentation boundary

- TUI-specific formatting/state rendering stays inside TUI layer only.

### R4. Observability parity for TUI lane

- TUI lane logs/metrics identify adapter lane and canonical event type.

## Acceptance Criteria

1. TUI realtime updates are sourced from canonical adapter contract.
2. TUI bypass path for core output progression is removed.
3. TUI presentation behavior remains local and does not mutate canonical payload semantics.
4. TUI-focused tests validate canonical contract path and regressions.

## Risks

- Rendering adapters may assume legacy payload shape and require compatibility shims.
- Partial migration can create duplicate or out-of-order UI updates.

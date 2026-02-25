# Implementation Plan - ucap-tui-adapter-alignment

## Objective

Migrate TUI realtime behavior onto canonical adapter output while preserving TUI presentation responsibilities.

## Requirement Traceability

- `R1` -> Phase 1
- `R2` -> Phase 2
- `R3` -> Phase 2
- `R4` -> Phase 3

## Phase 1 - Wire TUI Lane to Canonical Contract

- [x] Route TUI output update path through canonical contract serializer path.
- [x] Verify required metadata fields are preserved for TUI consumers.

### Files (expected)

- `teleclaude/cli/*`
- `teleclaude/core/*`

## Phase 2 - Remove TUI Bypass and Preserve Presentation Boundaries

- [x] Remove direct TUI bypass path for core output progression.
- [x] Keep TUI presentation logic in TUI components only.
- [x] Ensure canonical contract remains source-of-truth payload.

### Files (expected)

- `teleclaude/cli/*`
- shared adapter/realtime modules under `teleclaude/core/*`

## Phase 3 - TUI Validation and Observability

- [ ] Add tests for canonical contract path in TUI lane.
- [ ] Add/verify TUI lane observability fields (lane, event type, session).

### Files (expected)

- `tests/unit/*tui*`
- `tests/integration/*`

## Definition of Done

- [ ] TUI lane uses canonical outbound contract.
- [ ] TUI bypass path is removed for core output progression.
- [ ] TUI presentation boundary remains intact.

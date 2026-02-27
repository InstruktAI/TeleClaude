# DOR Report: tui-footer-key-contract-restoration

## Draft Assessment

**Assessed at:** 2026-02-27 (draft phase)
**Assessed by:** Prepare router (draft inline)

### Gate 1: Intent & Success

**Status:** Pass

- Problem statement is explicit: complete the key-contract gaps in the TUI footer system.
- The "what" and "why" are captured in `requirements.md` with per-node contracts.
- Success criteria are concrete and testable (specific key → action mappings per node type).

### Gate 2: Scope & Size

**Status:** Pass with notes

- The work is bounded: 4 phases, each independent enough for focused commits.
- Cross-cutting: the `NewProjectModal` is shared between Sessions and Preparation views. Called out explicitly.
- Risk: Phase 2 (prep computer grouping) involves tree restructuring which could be larger than expected. The preparation view's data model may need changes beyond just mounting a `ComputerHeader`.

### Gate 3: Verification

**Status:** Pass

- Tests are specified per phase (check_action tests, modal validation tests, tree structure tests).
- Edge cases identified: `~` resolution, duplicate project/path, inline error display.
- Demo plan covers all observable behaviors.

### Gate 4: Approach Known

**Status:** Pass

- Sessions view patterns (check_action, action routing, tree building) are well-established.
- `ComputerHeader` widget already exists and is reusable for prep view.
- Modal pattern (`ModalScreen[T]`) is proven via `StartSessionModal`, `ConfirmModal`, `CreateSlugModal`.
- Config patch via `telec config patch` is the known mechanism for trusted_dirs updates.

### Gate 5: Research Complete

**Status:** N/A (no third-party dependencies)

### Gate 6: Dependencies & Preconditions

**Status:** Pass

- No prerequisite todos. Work builds on the delivered footer migration.
- Config system (`telec config patch`) is available and tested.
- No new env vars or external systems required.

### Gate 7: Integration Safety

**Status:** Pass

- Changes are additive — existing behavior only changes for Enter-on-ComputerHeader (from restart_all to path-mode modal).
- Rollback: revert the `action_focus_pane` routing change restores prior behavior.
- Each phase can be shipped independently.

### Gate 8: Tooling Impact

**Status:** N/A (no tooling/scaffolding changes)

## Open Questions

1. **`n` key conflict on sessions view:** Currently `n` is bound to `new_session`. The requirements want `n` on computer nodes to open `NewProjectModal` and `n` on project nodes to open `StartSessionModal`. This requires either two separate action names (`new_project` vs `new_session`) both bound to `n` with `check_action` gating, or a single action that dispatches by node type. The plan proposes separate actions — gate worker should validate this is achievable with Textual's binding system (two bindings to same key with different action names, only one enabled at a time via check_action).

2. **Preparation view data model:** The current prep view builds its tree from a flat project→todo structure. Adding computer grouping requires understanding how computers are resolved for each todo. The `_slug_to_computer` dict exists but may not cover all cases. Gate worker should verify the data flow.

## Assumptions

- The `ComputerHeader` widget from the sessions view can be reused as-is in the preparation view without modification.
- `telec config patch` supports appending to `computer.trusted_dirs` array entries.
- Textual allows multiple bindings to the same key with different action names, disambiguated by `check_action()`.

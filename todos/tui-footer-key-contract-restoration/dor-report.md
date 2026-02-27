# DOR Report: tui-footer-key-contract-restoration

## Gate Verdict

**Assessed at:** 2026-02-27T13:15:00Z
**Assessed by:** Gate worker (formal DOR validation)
**Score:** 9 / 10
**Status:** pass

## Gate Assessment

### Gate 1: Intent & Success — PASS

- Problem statement is explicit: complete remaining key-contract gaps in TUI footer system.
- The "what" and "why" are captured in `requirements.md` with per-node contracts for Sessions and Todo tabs.
- Success criteria are concrete and testable: specific key → action mappings per node type, modal validation behavior, tree hierarchy structure.

### Gate 2: Scope & Size — PASS

- Four independent phases, each suitable for focused commits.
- Cross-cutting concern (NewProjectModal shared between Sessions and Preparation views) is explicitly called out and handled by a dedicated task (3.3).
- Phase 2 (prep computer grouping) is the largest piece. Verified: `_slug_to_computer` mapping exists (preparation.py line 77), `ComputerHeader` is reusable, data structures support the tier addition with depth adjustments only.

### Gate 3: Verification — PASS

- Tests are specified per phase: check_action coverage, modal validation, tree structure.
- Edge cases identified: `~` resolution, duplicate project/path detection, inline error display.
- Demo plan covers all observable behaviors across both tabs.

### Gate 4: Approach Known — PASS

- **Dual-key binding (former blocker — resolved):** The sessions view already uses `R` bound to both `restart_session` and `restart_all` with `check_action()` dispatch. The `n` key (`new_project` vs `new_session`) follows the identical pattern. No design unknowns.
- **Preparation tree grouping (former blocker — resolved):** `_slug_to_computer` dict exists and is populated during rebuild. `ComputerHeader` is generic and reusable (only needs `ComputerDisplayInfo`). Work is tree-depth adjustment — no model redesign.
- Modal pattern (`ModalScreen[T]`) is proven via `StartSessionModal`, `ConfirmModal`, `CreateSlugModal`.

### Gate 5: Research Complete — N/A

No third-party dependencies.

### Gate 6: Dependencies & Preconditions — PASS

- No prerequisite todos. Work builds on the delivered footer migration.
- Config system available. **Implementation note:** `telec config patch` uses `_deep_merge` which replaces arrays (not appends). Builder must read current `trusted_dirs`, append in memory, then patch with the full array. This is a known pattern, not a blocker.
- No new env vars or external systems required.

### Gate 7: Integration Safety — PASS

- Changes are additive. Only behavioral change: Enter on ComputerHeader routes to path-mode modal instead of restart_all.
- Rollback: revert the `action_focus_pane` routing change restores prior behavior.
- Each phase can be shipped independently.

### Gate 8: Tooling Impact — N/A

No tooling or scaffolding changes.

### Plan-to-Requirement Fidelity — PASS

Every implementation plan task traces to a requirement:

- Task 1.1 ← Enter on computer opens path-mode modal
- Task 1.2 ← R on project restarts project sessions
- Task 1.3 ← Global visibility audit
- Task 2.1 ← Computer grouping in prep tree
- Task 2.2 ← check_action for computer nodes in prep view
- Task 3.1 ← StartSessionModal path-input mode
- Task 3.2 ← NewProjectModal creation
- Task 3.3 ← New Project wiring into views
- Task 4.x ← Test coverage for all above

No contradictions found between plan and requirements.

## Resolved Blockers

| Blocker                                          | Resolution                                                                                                                        |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Textual dual-key binding feasibility for `n` key | Sessions view already uses `R` → `restart_session` / `restart_all` with `check_action()` dispatch. Proven pattern.                |
| Preparation view data flow for computer grouping | `_slug_to_computer` mapping exists at line 77, `ComputerHeader` is generic and reusable, depth adjustments are minor scaffolding. |

## Implementation Notes for Builder

1. **Array merge caveat:** `telec config patch --yaml` uses deep merge that replaces arrays. For `trusted_dirs`, read current value first, append new entry, then patch with the full array.
2. **Dual-key pattern:** Follow the `R` key precedent in sessions.py — two `Binding` entries with different action names, both gated by `check_action()`.
3. **Prep tree depth:** Account for the extra ComputerHeader tier in `_nav_items` depth tracking and `_resolve_project_header_for_index()`.

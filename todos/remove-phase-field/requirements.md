# Requirements: remove-phase-field

## Goal

Remove the `phase` field from `state.yaml` and all code that reads/writes it. Replace all `phase` checks with equivalent `build`/`review` checks. The system behavior must remain identical.

## Scope

### In scope:

- Remove `ItemPhase` enum and all `phase` read/write/check functions
- Replace `phase`-based checks with `build`-based equivalents
- Update `DEFAULT_STATE` to remove `phase`
- Update `TodoState` pydantic model to remove `phase`
- Update TUI types that reference phase
- Update roadmap.py phase derivation
- Update all tests that set or assert `phase`
- Remove migration code for `phase` (lines 347-356 in core.py)
- Update `todo_scaffold.py` default state template

### Out of scope:

- Changes to the finalize flow (already removes from roadmap, no `phase: done` involved)
- Changes to the `mark_phase` MCP tool (confusingly named but operates on `build`/`review`, not `phase`)
- Changes to `PhaseName` enum (refers to `build`/`review`, not `phase`)

## Success Criteria

- [ ] `phase` field no longer exists in `state.yaml` schema or defaults
- [ ] `ItemPhase` enum removed
- [ ] `get_item_phase`, `set_item_phase` functions removed
- [ ] All checks that used `phase == pending` now use `build == pending`
- [ ] All checks that used `phase == in_progress` now use `build != pending`
- [ ] All checks that used `phase == done` either removed (dead code) or use `not in roadmap`
- [ ] Claim/lock at dispatch point uses `build: started` instead of `phase: in_progress`
- [ ] `is_ready_for_work` checks `build == pending` instead of `phase == pending`
- [ ] All existing tests pass (updated to remove phase references)
- [ ] `make lint` passes
- [ ] TUI displays correct status without `phase`

## Constraints

- Zero behavior change. Every code path must produce the same outcome.
- The `mark_phase` MCP tool name stays the same (it marks `build`/`review`, not `phase`).
- Existing `state.yaml` files in the wild that still have `phase` must not break on read (graceful ignore).

## Key Insight

`phase: done` is a phantom state. It's defined in the `ItemPhase` enum but **never written** by any production code. The finalizer removes the slug from roadmap and deletes the todo directory — the item's absence IS completion. All dependency checks already handle "not in roadmap = satisfied" as their primary path. The `phase == done` checks in the codebase are dead code.

## Risks

- Any consumer of `phase` outside the traced code paths (agent artifacts, skill prompts referencing `phase`). Mitigate with grep across the entire repo including markdown/yaml files.
- Cross-todo coordination: `lifecycle-enforcement-gates` implementation plan references `set_item_phase` — that plan should be updated after this change lands.

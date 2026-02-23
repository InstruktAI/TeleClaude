# Input: remove-phase-field

The `phase` field in `state.yaml` (`pending`, `in_progress`, `done`) is redundant with the existing `build` and `review` statuses. It adds confusion without providing information that can't be derived from the other fields.

## Evidence from code analysis

1. **`phase: done` is never written by any production code.** Only `set_item_phase` writes `phase`, and it's only called once in production: `core.py:2119` setting `in_progress`. The finalize flow removes the todo from roadmap entirely — it never sets `phase: done`.

2. **The migration code already proves derivability.** `read_phase_state()` at lines 347-353 derives `phase` from `build` when `phase` is missing:
   - `build != pending` → `phase = in_progress`
   - `build == pending` → `phase = pending`

3. **`phase: in_progress` is set 5 lines before `build: started`** (core.py:2119 vs 2124). They're set in the same function call. The "lock" that `phase: in_progress` provides could be achieved by setting `build: started` at the same point.

4. **Dependency checks use `phase: done` but it's dead code.** `check_dependencies_satisfied` checks `phase == done` (line 839), but since finalize removes slugs from roadmap, the "not in roadmap" fallback (line 834-836) is what actually fires. The `done` check is unreachable in practice.

5. **The TUI already derives display status from `build`/`review`** (roadmap.py:129-134), falling back to phase only as a secondary signal.

## Desired outcome

Remove `phase` from `state.yaml` and derive item lifecycle state from `build` + `review`:

- **Not started**: `build == pending`
- **In progress**: `build != pending` (started or complete)
- **Done**: item removed from roadmap (existing behavior, unchanged)

This eliminates a confusing field that adds no information the system doesn't already have.

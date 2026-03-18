# Input: mark-phase-force

## Problem

`telec todo mark-phase` enforces several prerequisite guards before it will update
state.yaml:

- **Worktree must exist** at `trees/{slug}/` — blocks setting build/review phases when
  no worktree has been created yet (e.g. a todo that was prepared inline on main).
- **No uncommitted changes** — blocks marking terminal statuses when the tree is dirty.
- **No stash entries** — blocks marking terminal statuses when stash has entries.

These guards protect against accidents in normal flow. But they also make it impossible
for agents (and humans) to directly override or correct state without satisfying all
preconditions. There is no escape hatch.

## Pain

Agents struggle to navigate the state machine's richness. They shouldn't have to. When
an agent or human needs to set a specific phase to a specific value — because something
went wrong, because they prepared inline, or because the state drifted — they cannot do
it without first satisfying guards that may be irrelevant to their intent.

`telec todo mark-ready` partially fills this gap (it normalizes the full prepare state),
but it only covers "ready for build" and requires artifacts to exist. It's too coarse and
too opinionated for state correction.

## Fix

Add `--force` flag to `telec todo mark-phase`. When set:

- Skip worktree existence check — if worktree exists, use it; if not, fall back to `cwd`.
- Skip uncommitted changes check.
- Skip stash check.
- All other behavior (phase routing, state write) is unchanged.

The result: agents and humans can set any supported phase to any valid value without
fighting prerequisites. One sharp, transparent tool.

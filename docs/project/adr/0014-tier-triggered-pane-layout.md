---
id: 'project/adr/0014-tier-triggered-pane-layout'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '14'
date: '2026-06-03'
adr_status: 'accepted'
description: 'The Sessions-view pane renderer swaps same-tier cells in place and minimally reflows on tier change, replacing the destroy-and-rebuild + select-layout even-horizontal approach; one canonical state owner enforces invariant I1.'
---
# ADR-0014: Tier-Triggered In-Place Pane Layout — ADR

## Context

The Sessions-view tmux pane subsystem produced repeated, hard-to-kill UX
regressions:

- **Three interaction paths, one sticky-aware.** Keyboard Space routed through a
  sticky-aware decision, but mouse single-click and Enter assigned the preview
  directly. Selecting an already-sticky session set `preview == a sticky`,
  rendering a duplicate pane where the preview window should be.
- **The documented model was dead code.** A reducer/controller (`TuiState`,
  `reduce_state`, `TuiController`) encoded the invariants but was referenced only
  by tests; production layout state lived on the Sessions view and a bridge
  mirror that enforced nothing. A corrupt `preview in sticky` snapshot was
  persisted and survived restarts.
- **Destroy-and-rebuild renderer.** Every layout change killed tracked panes and
  re-split, then ran `select-layout even-horizontal` for 3-column layouts.
  `even-horizontal` counts *live* panes, so any orphan (a live pane untracked in
  `session_to_pane`, e.g. left by a crashed reflow) became an extra column —
  the "5 columns, last two bottom-half only dots" failure. Same-tier transitions
  (e.g. un-stickying one of five stickies) rebuilt the whole grid even though the
  pane count never changed.

We needed a single state model with a structural no-duplicate guarantee, and a
renderer that does the minimum tmux work and cannot leak columns.

## Decision

- **One state owner + invariant I1.** The Sessions view owns `sticky_ids` +
  `preview_id`; the pane bridge mirror is re-synced from it on every data
  refresh. Invariant I1 (`preview_id` never in `sticky_ids`) is enforced at every
  mutation boundary — all preview gestures (click, Enter, Space) route through
  one sticky-aware selector — and on persisted-state load (self-heal). The pure
  model (`desired()`, `enforce_i1()`, `diff_cells()`, `orphan_panes()`) lives in
  `teleclaude/cli/tui/layout_model.py`. The dead reducer/controller is deleted.
- **Tier-triggered, in-place rendering.** `desired(sticky_ids, preview_id)`
  derives the ordered non-TUI cell assignment, including the five-sticky borrow
  rule (the last sticky cell is borrowed for the preview and reverts when it
  clears). `tier = 1 + len(desired)`. Same-tier transitions `respawn-pane -k`
  only the cells whose session changed. Tier changes apply a minimal tmux delta:
  surviving session panes stay mapped to their pane ids, added cells are split,
  removed cells are killed, and the 4↔5 boundary uses explicit pane moves because
  the TUI pane changes between top-left and full-left shapes.
- **Explicit widths, orphan reaping.** `select-layout even-horizontal` is removed;
  3-column widths come from explicit split percentages so the column count is
  bounded by the grid, not by the live-pane count. At render entry, live non-TUI
  panes that no tracked session maps to are reaped; tracked panes are never
  touched by this sweep.
- **Clockwise, index-preserving grids.** `LAYOUT_SPECS` numbers cells clockwise
  from the cell nearest the TUI; tui+4 lets the TUI span the full left column, and
  tui+4 → tui+5 only adds the bottom-left cell.

## Consequences

**Positive:**

- Selecting a sticky can no longer duplicate it as a preview — the guarantee is
  structural, not a per-call check.
- Same-tier transitions cause no grid churn and no column explosion; the
  un-sticky-from-five case stays a single in-place swap.
- ~850 lines of dead reducer/controller code are gone; there is one model to
  reason about and test.
- The pure layout logic is unit-tested (truth table, I1 self-heal, diff, orphan
  reaping) independent of tmux.

**Negative / costs:**

- Minimal tier reflow is more complex than clean rebuild, especially at the 4↔5
  boundary where pane ids must survive while tmux geometry changes shape. That
  path now depends on explicit `swap-pane` / `join-pane` operations in addition
  to split/kill.
- The renderer's correctness across the multi-pane session grid (tiers 5/6) is a
  runtime/visual property, so it is covered by a tmux-backed functional test that
  exercises tui+3 → tui+4 → tui+5 and the five-sticky preview borrow/revert.
- Doc previews are diffed by `(session_id, command)` so a command change on the
  same doc still respawns in place; this couples the cell fingerprint to the
  command string.

## Alternatives Considered

- **Keep the reducer/controller and wire it into production.** Rejected: it
  duplicated the view's state, added a second source of truth to keep in sync, and
  nothing demonstrated it was simpler than enforcing I1 at the view's mutation
  boundary.
- **Reap orphans before `even-horizontal` and keep the rebuild renderer.** Reaping
  fixes the orphan-column symptom, but the destroy-and-rebuild churn on every
  same-tier change (and the focus/flicker cost) remained. Removing
  `even-horizontal` and rebuilding only on tier change addresses the root cause.
- **Clean rebuild on tier change.** Simpler, but it destroys stable panes that
  still belong in the desired layout and creates avoidable flicker/focus churn.
  Rejected because the approved renderer contract requires stable panes to
  survive adjacent tier changes.

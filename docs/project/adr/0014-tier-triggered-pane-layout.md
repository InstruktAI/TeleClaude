---
date: '2026-06-03'
description: 'The Sessions-view pane renderer swaps same-tier cells in place and minimally reflows on tier change, replacing the destroy-and-rebuild + select-layout even-horizontal approach; one canonical state owner enforces invariant I1.'
number: '14'
visibility: 'public'
---

# ADR-0014: Tier-Triggered In-Place Pane Layout — ADR

## Context

The Sessions-view tmux pane subsystem produced repeated, hard-to-kill UX regressions, tracing to two root causes: there was no single owner of layout state (several interaction paths mutated it independently, and a documented reducer model existed only in tests while production state lived elsewhere and enforced nothing), and the renderer destroyed and rebuilt every pane on any change, then ran `even-horizontal` — which counts live panes, so any orphan became a phantom extra column. We needed one state model with a structural no-duplicate guarantee and a renderer that does minimal work and cannot leak columns.

## Decision

- **One canonical state owner enforcing invariant I1.** A single owner holds the sticky and preview state; the invariant that the preview is never also a sticky is enforced at every mutation boundary — all selection gestures route through one sticky-aware path — and self-healed on persisted-state load. The dead duplicate reducer/controller is deleted.
- **Tier-triggered, in-place rendering.** Same-tier transitions respawn only the cells whose session changed; tier changes apply a minimal delta (surviving panes keep their ids, added cells split, removed cells are killed). The renderer does the least tmux work that reaches the desired layout.
- **Explicit widths, orphan reaping.** `even-horizontal` is removed; column widths come from explicit split percentages, so the column count is bounded by the grid, not the live-pane count. At render entry, untracked panes are reaped; tracked panes are never touched.

## Consequences

- Selecting a sticky can no longer duplicate it as a preview — the guarantee is structural, not a per-call check.
- Same-tier transitions cause no grid churn and no column explosion.
- A large body of dead reducer/controller code is gone; there is one model to reason about and test.
- Cost: minimal tier reflow is more complex than a clean rebuild, especially where pane geometry changes shape while pane ids must survive; that path is covered by a tmux-backed functional test rather than pure-unit checks.

## Alternatives Considered

- **Keep the reducer/controller and wire it into production.** Rejected: it duplicated the view's state, adding a second source of truth, with nothing showing it was simpler than enforcing the invariant at the view's mutation boundary.
- **Reap orphans but keep the destroy-and-rebuild renderer.** Rejected: reaping fixes the orphan-column symptom but leaves the rebuild churn and flicker on every same-tier change.
- **Clean rebuild on tier change.** Rejected: it destroys stable panes that still belong in the layout, creating avoidable flicker and focus churn.

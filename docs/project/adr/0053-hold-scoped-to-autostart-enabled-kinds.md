---
visibility: public
number: 53
date: 2026-06-19
description: Hold applies only while a todo kind's autostart policy is enabled; autostart-disabled kinds do not write, render, or offer hold.
---

# ADR-0053: Hold scoped to autostart-enabled kinds — ADR

## Status

Superseded in part by ADR-0061. Hold persistence, rendering, and autonomous
dispatch effect are no longer scoped to autostart-enabled work-lane todos; this
record remains the historical rationale for the discarded autostart-scoped
model.

## Context

Hold is the persisted operator brake for automatic entry into lifecycle work. The
autostart policy is also kind-scoped, and an operator can turn autostart off for a
kind to keep that kind out of automatic work dispatch. Treating hold as
independent from that policy leaves redundant state: a manual close or silent
creation can set a hold flag for work the runner is already barred from starting,
and the TUI can render a lock for a control surface that is dormant.

ADR-0036 chose that a manual close writes hold so a human kill reliably halts
runaway work. That remains correct for autostart-enabled kinds. The contested
case is a kind whose autostart is disabled: preserving the halt durability there
would make a hidden hold survive until autostart is later enabled, while removing
it lets enabling autostart resume all work of that kind immediately.

## Decision

Hold is scoped to known kinds whose autostart policy is enabled. A hold request
for a known autostart-disabled kind writes no hold flag and no hold audit, and a
residual hold flag on such a kind is inert for automatic dispatch and row
rendering. Kindless todos keep their parking hold because no per-kind policy
applies until classification.

Manual start is the operator's one-way-forward path and does not read hold. Hold
brakes automatic work-lane dispatch only; it does not block an explicit operator
start or adoption.

This reverses ADR-0036 only for the autostart-disabled case. A manual close of
an autostart-enabled kind still writes hold. A manual close of an
autostart-disabled kind writes no hold, and the durability concern is waived:
turning autostart on is intended to resume work for that kind cleanly rather than
preserve prior parked state.

## Consequences

- Autostart off means the whole hold surface is dormant for that kind: no set,
  no lock glyph, and no hold control.
- Enabling autostart for a kind resumes that kind without clearing legacy hold
  flags first; residual flags are ignored while disabled and become effective
  only if still present when autostart is enabled.
- Manual start stays usable as the explicit operator path through a held todo.
- Kindless parking remains available before classification, so raw dumps can
  still be intentionally parked.
- The runner and TUI must derive hold effect from the same predicate so set,
  dispatch, and render behavior do not drift.

## Alternatives Considered

- **Keep manual-close hold durable even when autostart is disabled.** Rejected:
  it preserves runaway-halt protection for a surface the operator explicitly
  disabled, at the cost of stale hidden state when the operator later enables
  autostart.
- **Render residual holds but hide the control.** Rejected: it exposes a lock for
  a dormant control surface and gives the operator no coherent action to take.
- **Clear residual holds automatically when autostart is disabled.** Rejected:
  the decision only needs the disabled-kind surface to be inert. Clearing stored
  legacy state would add a migration/mutation path without changing observable
  disabled-state behavior.

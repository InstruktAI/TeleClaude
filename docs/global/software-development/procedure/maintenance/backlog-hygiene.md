---
id: 'software-development/procedure/maintenance/backlog-hygiene'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Backlog hygiene rules to keep work small, explicit, and decision-ready.'
---

# Backlog Hygiene — Procedure

## Goal

Keep backlog quality high enough that prioritization is fast and obvious.

## Preconditions

- Backlog states are standardized.
- WIP limits are agreed.
- Weekly hygiene pass is part of maintenance cadence.

## Steps

1. Use explicit states only:
   - Inbox,
   - Ready,
   - Doing,
   - Blocked,
   - Done,
   - Closed.
2. Enforce WIP limits:
   - max active `Doing` items,
   - explicit cap on aged blocked items.
3. During weekly hygiene pass:
   - empty Inbox through triage,
   - deduplicate,
   - force decision on blocked >7 days,
   - re-evaluate stale Ready items,
   - close low-value leftovers.
4. Keep Ready-state quality bar strict:
   - clear problem,
   - expected outcome,
   - acceptance check,
   - known dependencies.

## Outputs

- Smaller active work surface.
- Fewer stale and undefined items.
- Clear weekly priorities.
- Better predictability for delivery and maintenance.

## Recovery

If backlog becomes noisy or overloaded:

1. Freeze new non-critical intake briefly.
2. Prune duplicates and low-value items aggressively.
3. Restore WIP limits before starting additional work.
4. Re-run triage on old items with current reality, not historical intention.

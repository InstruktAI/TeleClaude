---
description: 'Process deferrals, create new todos, and mark deferrals as processed.'
visibility: 'public'
---

# Deferrals — Procedure

## Goal

- Process deferrals into new todos or mark as no-ops, then record completion.

## Preconditions

- `telec todo artifacts read {slug} deferrals` exists.
- A deferrals artifact exists and has not been processed.

## Steps

1. Read `telec todo artifacts read {slug} deferrals`.
2. For each deferral entry:
   - If `Suggested outcome` is `NEW_TODO`, create a new, independent todo with
     `telec todo create <new_slug> --kind <kind>` — never `--group {slug}`.
     Grouping is reserved for prepare-phase scope-splitting (a planner
     decomposing an oversized plan into children); it strips the parent's
     lifecycle state and must never be used to attach a deferred follow-up to a
     todo that is already mid-flight or finalizing. Add `--after {slug}` only
     when the deferred item has a genuine technical dependency on this todo;
     otherwise it stands on its own.
   - If `Suggested outcome` is `NOOP`, mark the entry as processed.
3. Stamp processing complete:
   - `telec todo stamp {slug} --deferrals-processed`
4. Commit all changes and report a summary.

## Outputs

- Deferrals processed and stamped.
- New todos created when required.

## Recovery

- If deferrals file is missing, stop and report; do not mark processed.

---
description: 'Process deferrals, create new todos, and mark deferrals as processed.'
id: 'software-development/procedure/lifecycle/work/deferrals'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Deferrals — Procedure

## Goal

- Process deferrals into new todos or mark as no-ops, then record completion.

## Preconditions

- `telec todo artifacts read {slug} deferrals` exists.
- A deferrals artifact exists and has not been processed.

## Steps

1. Read `telec todo artifacts read {slug} deferrals` and `todos.db` state.
2. For each deferral entry:
   - If `Suggested outcome` is `NEW_TODO`, create a new todo with `input.md`, add to roadmap, and add dependencies if needed.
   - If `Suggested outcome` is `NOOP`, mark the entry as processed.
3. Stamp processing complete:
   - `telec todo stamp {slug} --deferrals-processed`
4. Commit all changes and report a summary.

## Outputs

- Deferrals processed and stamped.
- New todos created when required.

## Recovery

- If deferrals file is missing, stop and report; do not mark processed.

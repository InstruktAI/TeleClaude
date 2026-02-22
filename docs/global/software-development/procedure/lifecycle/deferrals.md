---
description: 'Process deferrals, create new todos, and mark deferrals as processed.'
id: 'software-development/procedure/lifecycle/deferrals'
scope: 'domain'
type: 'procedure'
---

# Deferrals — Procedure

## Goal

- Process deferrals into new todos or mark as no-ops, then record completion.

## Preconditions

- `todos/{slug}/deferrals.md` exists.
- `todos/{slug}/state.yaml` exists and `deferrals_processed` is false.

## Steps

1. Read `todos/{slug}/deferrals.md` and `todos/{slug}/state.yaml`.
2. For each deferral entry:
   - If `Suggested outcome` is `NEW_TODO`, create a new todo with `input.md`, add to roadmap, and add dependencies if needed.
   - If `Suggested outcome` is `NOOP`, mark the entry as processed.
3. Update `state.yaml`:
   - Set `deferrals_processed` to true.
   - Store `deferrals_hash` as SHA256 of `deferrals.md`.
4. Commit all changes and report a summary.

## Outputs

- Deferrals processed and recorded.
- New todos created when required.

## Recovery

- If deferrals file is missing, stop and report; do not mark processed.

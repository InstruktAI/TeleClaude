---
description: Process deferrals, create new todos, and mark deferrals as processed.
id: software-development/procedure/lifecycle/deferrals
scope: domain
type: procedure
---

# Lifecycle: Deferrals Processing

## 1) Load Context

1. Read `todos/{slug}/deferrals.md` (stop if missing).
2. Read `todos/{slug}/state.json` and ensure `deferrals_processed` is not true.

## 2) Process Each Deferral

For each entry:

- If `Suggested outcome` is `NEW_TODO`:
  - Create a new todo slug derived from the title.
  - Create `todos/{new_slug}/input.md` with Title, Why deferred, Decision needed, and link to original slug.
  - Add `{new_slug}` to `todos/roadmap.md` (pending `[ ]`).
  - If new todo depends on `{slug}`, add dependency in `todos/dependencies.json`.
  - Mark deferral entry as processed with the new slug.

- If `Suggested outcome` is `NOOP`:
  - Mark deferral entry as processed.

## 3) Update State

Update `todos/{slug}/state.json`:

- Set `deferrals_processed` to true.
- Store `deferrals_hash` as SHA256 of `deferrals.md`.

## 4) Commit

Commit all changes (new todos, roadmap, dependencies, state.json, deferrals.md).

## 5) Report

Report summary of actions taken (new todos created, NOOPs).

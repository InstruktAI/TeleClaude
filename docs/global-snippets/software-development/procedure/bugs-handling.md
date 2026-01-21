---
description:
  Triage bugs, decide quick fixes vs new todos, and track resolution in
  bugs.md.
id: software-development/procedure/bugs-handling
scope: domain
type: procedure
---

# Bugs Handling Procedure

## Goal

Convert raw bug reports into action: fix quickly when safe, otherwise create a todo with clear scope.

## 1) Load Bugs

- Read `todos/bugs.md`.
- Find unchecked items (`[ ]`).
- If none, report and stop.

## 2) For Each Bug

### 2.1 Understand

- Read the bug description.
- Identify affected files/components.
- Understand expected vs actual behavior.

### 2.2 Investigate

- Search the codebase and logs.
- Identify the root cause if possible.

### 2.3 Decide: Quick Fix or Todo

**Quick fix** if all are true:

- Small, localized change
- Low risk of regressions
- Clear expected outcome

**Otherwise create a todo**:

- Create `todos/{new_slug}/input.md` with the bug details
- Add `{new_slug}` to `todos/roadmap.md` as `[ ]`
- Mark the bug as converted (note the new slug)

### 2.4 If Quick Fix

- Mark `[>]` in `bugs.md` while working
- Apply minimal fix
- Verify via commit hooks (lint + unit tests)
- Mark `[x]` when fixed
- Commit one bug per commit

## 3) Report

Summarize fixes and any new todos created.

## Error Handling

- If not reproducible: add note and mark `[?]`
- If fix causes regression: document and mark `[!]`
- If stuck: document what was tried and continue

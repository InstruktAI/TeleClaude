---
description: Documentation discovery in a todo worktree reads a generated catalog that reflects the worktree's current project sources.
delivered_by:
  - fix-context-selection-repeatedly-cannot-find
---

# Worktree Documentation Index Readiness — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

A docs-capable todo worktree is ready for an agent only after its local project
documentation catalog reflects the sources present after the worktree baseline
is updated. Documentation discovery within that worktree uses the local catalog
and exposes its current project snippets.

## Canonical fields

### Use cases

#### UC-WDI1: Worktree readiness includes its current documentation catalog

```gherkin
Given an agent is about to enter a docs-capable todo worktree
And the worktree has no project documentation catalog or its project sources have changed
When the platform makes the worktree ready and dispatches the agent
Then documentation discovery from that worktree includes its current project snippets
And the agent receives no unavailable-catalog outcome for that documentation home
```

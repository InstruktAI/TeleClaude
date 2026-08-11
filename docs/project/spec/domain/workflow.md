---
visibility: internal
description: Frozen v1 ownership anchor for todos, artifacts, lifecycle state, and integration workflow.
---

# Workflow Domain Spec — Spec

## What it is

The v1 workflow area owns todo records, roadmap status, preparation artifacts,
lifecycle state, claims, worktree delivery, and integration coordination. Its
feature specs remain the current contract while autonomous dispatch is frozen.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/workflow/`.
- **Implementation roots:** `teleclaude/core/todos_db/`,
  `teleclaude/core/next_machine/`, `teleclaude/core/integration/`, and todo CLI
  handlers.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement work never uses this store or
  lifecycle.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md

---
visibility: internal
description: Frozen v1 ownership anchor for todos, artifacts, lifecycle state, and integration workflow.
---

# Workflow Domain Spec — Spec

## What it is

The v1 workflow area owns todo records, roadmap status, preparation artifacts,
lifecycle state, claims, worktree delivery, and integration coordination. Its
feature specs remain the current contract.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/workflow/`.
- **Implementation roots:** `teleclaude/core/todos_db/`,
  `teleclaude/core/next_machine/`, `teleclaude/core/integration/`, and todo CLI
  handlers.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement work never uses this store or
  lifecycle.

### Ownership boundary

- **Owns:** todo and artifact records, preparation and delivery state
  transitions, claims, dependencies, worktree delivery, and integration
  coordination.
- **Does not own:** agent process lifecycle, provider transport, caller
  identity, or domain behavior delivered by a todo.
- **Published contracts:** todo and artifact commands, queries, lifecycle
  events, and explicit dispatch requests to agent runtime.
- **Also published:** where a project's shared state lives, given a project
  root. A primary checkout owns its own state and a linked worktree's state
  lives at the owning checkout — the relation this context creates and defines,
  which is why the answer is published from here rather than from the context
  that owns the project's configuration file. Consumers read it through this
  contract and never interpret git metadata themselves.
<!-- planned:agent-artifact-source-layout -->
- **Also owns:** the names of the todo-lifecycle commands — one
  domain-qualified value each — and its own emissions of them: dispatch
  requests, machine scripts, and procedure loads. A command whose meaning
  belongs to another context is named by that context; the shared name table in
  the codebase holds every value mechanically and confers no authority. The
  corpus those names are laid out in belongs to `context`; resolving a name to a
  document, the session record and title that carry it, and the live-session
  attribution query that matches it belong to `agent_runtime`, which this
  context consumes.
<!-- /planned:agent-artifact-source-layout -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md

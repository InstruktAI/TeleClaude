---
date: '2026-05-23'
description: 'The workflow domain has no "roadmap" concept. A todo is the single entity, ordered and dependency-gated; the v2 workflow crate''s separate RoadmapEntry is redundant and folds into Todo. "Roadmap" misnames a dependency-ordered todo list.'
number: '45'
visibility: 'public'
---

# ADR-0045: Workflow Domain Has No Roadmap Concept — ADR

## Context

The workflow domain is a minimal surface: features are placed as todos, ordered, and gated by dependencies — "ready for work" is derived from a todo's dependencies being delivered. That is the whole model.

"Roadmap" entered as the name of a v1 storage table and was then promoted in the v2 workflow crate to a first-class entity modeled 1:1 alongside the todo — a redundant split whose only distinct fields (ordering, frozen, commit hash) are plain todo attributes. The word also misleads: in industry usage "roadmap" denotes a strategic horizon of targets the system deliberately does not model.

## Decision

The workflow domain has exactly one entity: the **todo**. It carries its own ordering, frozen flag, dependency edges, lifecycle phase, and delivery metadata. There is no separate "roadmap" entity, table, or event family.

- The v2 workflow crate's separate roadmap entity folds into the todo; the roadmap-named table and events move onto a todo-named surface.
- v1's legacy `roadmap` internals stay until the v2 cutover replaces v1 wholesale — renaming code with a death date is pure churn.
- Agent- and human-facing surfaces drop "roadmap" as a _concept_ in favor of "todo"/"todo list" wherever it does not name a real structure, table, or event.

## Consequences

- One entity instead of a redundant 1:1 pair — less schema, fewer events, no synchronization between two near-identical records.
- The vocabulary matches what the system is: a dependency-ordered todo list, not a strategic roadmap.
- v1 and v2 diverge on naming until cutover; this is intentional and bounded.

## Alternatives Considered

- **Keep the roadmap entity as an "ordering view" separate from the todo.** Rejected: its fields prove it is not a distinct concept — it duplicates the todo. A separate entity earns its place only with independent identity and lifecycle.
- **Rename "roadmap" to "ordering" but keep it a separate primitive.** Rejected: a better name on a structure that should not exist is still the wrong structure.
- **Rename v1's internals too.** Rejected: v1 is replaced at cutover; renaming a load-bearing legacy table is churn against code with a death date.
- **Delete the v2 workspace and rebuild.** Rejected: the workspace and its plumbing are sound; only the roadmap modeling is wrong. A scoped rework, not a teardown.

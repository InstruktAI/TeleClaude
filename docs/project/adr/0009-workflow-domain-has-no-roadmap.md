---
id: 'project/adr/0009-workflow-domain-has-no-roadmap'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '9'
date: '2026-05-23'
adr_status: 'accepted'
description: 'The workflow domain has no "roadmap" concept. A todo is the single entity, ordered and dependency-gated; the v2 workflow crate''s separate RoadmapEntry is to be folded into Todo. v1''s legacy roadmap table/module names stay until cutover.'
---
# ADR-0009: Workflow Domain Has No Roadmap Concept — ADR

## Context

The workflow domain is the minimal, frictionless surface for autonomous AI development: features are placed as todos, ordered, and gated by dependencies — "ready for work" is derived from a todo's dependencies being delivered. That is the whole model.

The term "roadmap" entered the codebase as the name of the v1 storage table (and its assembly module, `roadmap.py`). In v1 it is load-bearing legacy: the SQL table is named `roadmap`, the cache scope and `workflow.roadmap.*` events use the literal, and `chore(roadmap)` is a parsed commit type.

The v2 `workflow` crate (delivered prematurely under `v2-mvp-bootstrap`) carried that name forward and promoted it to a first-class entity: a `RoadmapEntry` modeled 1:1 alongside `Todo`. Inspection of `crates/workflow/src/models.rs` shows the split is redundant — `Todo` and `RoadmapEntry` already share `slug`, `project_id`, `group`, `after`, `description`, and `delivered_at`; the only fields unique to `RoadmapEntry` are `position`, `frozen`, and `commit_hash`, all of which are plain attributes of a todo.

"Roadmap" is also the wrong word independent of the redundancy: in industry usage (Jira, GitHub Projects) it denotes a strategic horizon of targets the system deliberately does not model. The word misdirects every agent and human who reads it.

## Decision

The workflow domain has exactly one entity: the **todo**. It carries its own ordering (`position`), `frozen` flag, dependency edges (`after`), lifecycle phase, and delivery metadata (`delivered_at`, `commit_hash`). There is no separate "roadmap" entity, table, or event family in the intended shape.

- **v2 (`workflow` crate):** fold `RoadmapEntry`'s unique fields into `Todo`, remove `RoadmapEntry` and `service/roadmap.rs`, and rename the `roadmap` Postgres table and `workflow.roadmap.*` events onto a todo-named surface. Tracked by the `v2-workflow-drop-roadmap` todo. The current v2 workflow code does **not** represent the intended shape; this ADR does.
- **v1:** the legacy `roadmap` table, `roadmap.py`/`roadmap_tree.py` modules, identifiers, the `"roadmap"` cache scope, and the `chore(roadmap)` commit type stay as-is — v1 is replaced wholesale at cutover, so renaming its internals is churn against code with a death date.
- **Agent- and human-facing surfaces** (error/notification strings, doc-snippet prose) drop "roadmap" as a *concept* in favor of "todo"/"todo list" where it does not name a real v1/v2 structure, table, event, or legacy file.

## Consequences

**Positive:**

- One entity instead of a redundant 1:1 pair — less schema, fewer events, no synchronization between `Todo` and `RoadmapEntry`.
- The vocabulary matches what the system is: a dependency-ordered todo list, not a strategic roadmap.
- Agents reading the consolidated specs and this ADR get the intended shape directly, rather than inferring it from the prematurely-delivered v2 code.

**Negative:**

- The v2 `workflow` crate, its Postgres schema, and its `workflow.roadmap.*` events must change. This must land before or with `v2-workflow-cutover`, because post-cutover those events and that schema become a live contract.
- v1 and v2 diverge on naming until cutover: v1 keeps `roadmap`, v2 will not. This is intentional and bounded, but readers must hold both in mind during the transition.
- The v2 code in the tree contradicts this ADR until `v2-workflow-drop-roadmap` is done. Mitigated by an explicit pointer from the AGENTS.md v2 section to this ADR, not by a code marker.

## Alternatives Considered

- **Keep `RoadmapEntry` as an "ordering view" separate from `Todo`.** Rejected: the fields prove it is not a distinct concept — it duplicates the todo and adds three attributes. A separate entity earns its place only when it has independent identity and lifecycle; this does not.
- **Rename "roadmap" to "ordering"/"position" but keep it a separate primitive.** Rejected for the same reason — a better name on a structure that should not exist is still the wrong structure.
- **Rename v1's internals too, for consistency.** Rejected: v1 is replaced at cutover; renaming a load-bearing legacy table and its parsed commit type is pure churn for code with a death date.
- **Delete the v2 workspace and rebuild from scratch.** Rejected: the Rust workspace and its spec-agnostic plumbing crates are sound; only the `workflow` feature's roadmap modeling is wrong. The fix is a scoped rework, not a teardown.

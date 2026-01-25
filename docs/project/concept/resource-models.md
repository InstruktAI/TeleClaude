---
description:
  Core resource shapes for computers, projects, todos, sessions, and agent
  availability.
id: teleclaude/concept/resource-models
scope: project
type: concept
---

# Resource Models — Concept

## Purpose

- @docs/project/concept/glossary.md

- Define the canonical resource concepts used by cache, API, and UI.
- Resource shapes originate from core dataclasses in `teleclaude/core/models.py`.
- Project identifiers are derived from full paths, not repo metadata.

- **Computer**: identity, status, last_seen, system stats.
- **Project**: trusted directory metadata (name, description, path, computer).
- **Todo**: task summary scoped to a project path.
- **Session summary**: list-view state (id, title, status, timestamps, agent info).
- **Agent availability**: per-agent readiness for orchestration selection.

## Inputs/Outputs

- **Inputs**: core models and cached snapshots.
- **Outputs**: API and UI representations of resources.

## Invariants

- Resource shapes are stable across adapters.
- Project paths remain the canonical identifier in cache and API.

## Primary flows

- Core events update cache snapshots → API serves resource lists.
- UI renders resource summaries from cache without deep aggregates.

## Failure modes

- Diverging resource shapes cause cache/API incompatibility.
- Missing project path normalization causes duplicate project entries.

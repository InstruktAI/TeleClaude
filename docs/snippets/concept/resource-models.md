---
description:
  Core resource shapes for computers, projects, todos, sessions, and agent
  availability.
id: teleclaude/concept/resource-models
requires:
  - teleclaude/concept/glossary
scope: project
type: concept
---

## Purpose

- Define the canonical resource concepts used by cache, API, and UI.

## Inputs/Outputs

- Inputs: core models and cached snapshots.
- Outputs: API and UI representations of resources.

## Primary flows

- Computer: identity, status, last_seen, and system stats.
- Project: trusted directory metadata (name, description, path, computer).
- Todo: task summary scoped to a project path.
- Session summary: lightweight state for list views (id, title, status, timestamps, agent info).
- Agent availability: per-agent readiness for orchestration selection.

## Invariants

- Resource shapes originate from core dataclasses in teleclaude/core/models.py.
- Project identifiers are derived from full paths, not repo metadata.

## Failure modes

- Diverging resource shapes cause cache/API incompatibility.

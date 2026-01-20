---
id: teleclaude/concept/resource-models
type: concept
scope: project
description: Core resource shapes for computers, projects, todos, sessions, and agent availability.
requires:
  - glossary.md
---

Purpose
- Define the canonical resource concepts used by cache, API, and UI.

Resources
- Computer: identity, status, last_seen, and system stats.
- Project: trusted directory metadata (name, description, path, computer).
- Todo: task summary scoped to a project path.
- Session summary: lightweight state for list views (id, title, status, timestamps, agent info).
- Agent availability: per-agent readiness for orchestration selection.

Invariants
- Resource shapes originate from core dataclasses in teleclaude/core/models.py.
- Project identifiers are derived from full paths, not repo metadata.

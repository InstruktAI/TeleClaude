---
id: teleclaude/architecture/next-machine
type: architecture
scope: project
description: Stateless workflow engine that orchestrates prepare/build/review phases from project files.
requires:
  - ../concept/session-types.md
---

Purpose
- Orchestrate structured work items using file-based state.

Inputs/Outputs
- Inputs: roadmap, requirements, plans, and state.json within a worktree.
- Outputs: textual instructions for orchestrator tools and agent dispatch.

Primary flows
- next_prepare (Phase A) emits HITL instructions for architecting work.
- next_work (Phase B) emits deterministic build/review/fix cycles.
- Dependency gating prevents blocked work items from being claimed.

Invariants
- Next Machine is stateless; it derives state from project files.
- Worktree scripts must run in repo context to ensure file availability.

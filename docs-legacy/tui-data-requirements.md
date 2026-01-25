# TUI Data Requirements and API Mapping (Target)

This document maps each TUI view to the minimal API data it needs, using resource-only endpoints.

Source of truth:

- Resource models: `teleclaude/core/models.py`
- TUI models: `teleclaude/cli/models.py` (target aligned to API DTOs)

## Views and Data Needs

### Sessions View

Purpose: project-centric tree with AI-to-AI nesting.

Data needed:

- Computers (grouping, metadata)
- Projects (metadata only for tree nodes)
- Sessions summary (local and remote)

API mapping:

- GET /computers
- GET /projects?computer=\*
- GET /sessions?computer=\*
  - Unfiltered `/sessions` is allowed for a global view.

Live details:

- When a session node is expanded, subscribe to session details and events via WebSocket.
- Session summary refreshes via cache TTL (target 15s).

### Preparation View

Purpose: project list with todos and build or review status.

Data needed:

- Computers (grouping)
- Projects (metadata)
- Todos (per project)

API mapping:

- GET /computers
- GET /projects?computer=\*
- GET /todos?computer=_ or GET /todos?project=_ (unfiltered allowed when needed)

### Footer

Purpose: agent availability status.

API mapping:

- GET /agents/availability

## Startup Flow (Target)

1. TUI calls API for data, cache-backed:
   - /computers
   - /projects
   - /todos
   - /sessions
   - /agents/availability

2. TUI opens WebSocket:
   - Subscribes to resources by scope (computer, project)
   - Cache pushes updates when refresh completes

The cache should serve immediately and refresh in the background when stale.

Note:

- Project identifiers are derived from full paths, not repo metadata.

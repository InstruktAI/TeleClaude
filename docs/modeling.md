# Modeling Policy (Target)

This document defines how data models are structured across the codebase. It is the reference for builder AI work.

## Goals

- One source of truth for resource shapes.
- Pydantic validation only at system boundaries.
- No aggregate payloads in API responses.
- Consistent shapes across API, WS, and TUI.

## Source of Truth

Core resource models are defined as dataclasses in:
- `teleclaude/core/models.py`

These dataclasses are the canonical shapes for:
- Computers
- Projects
- Todos
- Sessions (summary only)
- Agent availability

## Boundary DTOs

API and WebSocket payloads use DTOs that map 1:1 to the core dataclasses:
- DTOs live with the adapters (target location: `teleclaude/api_models.py`).
- DTOs may add transport metadata only (example `computer`).
- DTOs are validated at the boundary only.

## Validation Policy

- Use Pydantic for request and response validation at API and WS boundaries.
- Do not use Pydantic inside core logic or cache internals.
- TypedDict should be limited to local helpers or short-lived internal payloads.

## Session Summary vs Detail

- API returns session summary only.
- Session detail and live events are delivered via WebSocket when expanded.

## Identifiers

- Project identifiers are derived from full paths, not repo metadata.
- Composite identity for scoped resources uses `{computer, project, session}` as needed.

## Implementation Notes

- Centralize mapping functions (core dataclasses -> DTOs) in a single module.
- Remove aggregate payloads (example "projects with todos") from API.
- Align TUI models with API DTOs; avoid new parallel shapes.

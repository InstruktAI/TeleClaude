---
id: standard/modeling-policy
type: standard
scope: project
description: Standards for data modeling, validation, and resource representation.
---

# Modeling Standard

## Principles
1. **Single Source of Truth**: Core models MUST be defined as dataclasses in `teleclaude/core/models.py`.
2. **Pydantic at Boundaries**: Validation via Pydantic is reserved for system boundaries (API, WS, MCP).
3. **No Aggregates**: API endpoints MUST return resource-only shapes; no deep nesting (e.g., "projects with todos").
4. **Canonical Identity**: Project IDs are derived from absolute filesystem paths.

## Layers
- **Core**: Plain dataclasses for business logic.
- **API/WS**: DTOs (Data Transfer Objects) mapping 1:1 to core dataclasses + transport metadata (e.g., `computer`).
- **TUI**: Models aligned with API DTOs to avoid parallel shapes.

## Validation
- request/response validation at API boundaries only.
- internal logic uses type hints and basic validation.
---
id: standard/modeling-policy
type: standard
scope: project
description: Standards for data modeling, validation, and resource representation.
---

## Rule

- Core models are dataclasses in `teleclaude/core/models.py`.
- Pydantic validation is used only at system boundaries (API, WS, MCP).
- API responses are resource-only (no nested aggregates).
- Project IDs are derived from absolute filesystem paths.
- Transport DTOs map 1:1 to core dataclasses plus transport metadata.

## Rationale

- Keeps core logic simple, stable, and boundary-validated.

## Scope

- Applies to all data modeling and API representation work.

## Enforcement or checks

- Review new models for core/DTO separation.
- Reject API shapes that embed aggregates.

## Exceptions or edge cases

- None; deviations create incompatible data contracts.

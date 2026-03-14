---
id: 'project/policy/data-modeling'
type: 'policy'
scope: 'project'
description: 'Data modeling, validation, and resource representation rules.'
---

# Data Modeling — Policy

## Rules

- Core models are dataclasses in `teleclaude/core/models.py`.
- Pydantic validation is used only at system boundaries (API, WS).
- API responses are resource-only (no nested aggregates).
- Project IDs are derived from absolute filesystem paths.
- Transport DTOs map 1:1 to core dataclasses plus transport metadata.
- Changes to core models must include migration or backward-compatibility notes.

## Rationale

- Keeps core logic simple, stable, and boundary-validated.

## Scope

- Applies to all data modeling and API representation work.

## Enforcement

- Review new models for core/DTO separation.
- Reject API shapes that embed aggregates.

## Exceptions

- None; deviations create incompatible data contracts.

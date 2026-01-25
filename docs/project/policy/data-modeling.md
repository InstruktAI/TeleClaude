---
id: policy/data-modeling
type: policy
scope: project
description: Data modeling, validation, and resource representation rules.
---

# Data Modeling — Policy

## Rule

- Core models are dataclasses in `teleclaude/core/models.py`.
- Pydantic validation is used only at system boundaries (API, WS, MCP).
- API responses are resource-only (no nested aggregates).
- Project IDs are derived from absolute filesystem paths.
- Transport DTOs map 1:1 to core dataclasses plus transport metadata.

- Keeps core logic simple, stable, and boundary-validated.

- Applies to all data modeling and API representation work.

- Review new models for core/DTO separation.
- Reject API shapes that embed aggregates.

- None; deviations create incompatible data contracts.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.

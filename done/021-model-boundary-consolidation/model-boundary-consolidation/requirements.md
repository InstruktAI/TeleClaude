# Requirements - model-boundary-consolidation

## Goal

Consolidate resource shapes into a single source of truth and use Pydantic only at system boundaries.

## Non-Goals

- No behavioral changes to the daemon beyond data shape normalization.
- No changes to user-facing features beyond consistent payloads.
- No cache policy changes.

## Functional Requirements

1) **Single Source of Truth**
   - Core resource models live in `teleclaude/core/models.py` as dataclasses.
   - Resource identifiers are stable and derived from existing model fields.

2) **Boundary Validation Only**
   - Pydantic is used at REST and WebSocket boundaries for input and output validation.
   - Internal layers do not depend on Pydantic models.

3) **DTO Layer**
   - Introduce explicit DTOs for REST and WS payloads.
   - DTOs map 1:1 to core resource models (no new fields except transport metadata like `computer`).

4) **Remove Ad-Hoc Shapes**
   - Replace TypedDict response payloads for REST and WS with DTOs.
   - Remove aggregate or mixed-resource payloads from REST responses.

5) **Client Alignment**
   - `teleclaude/cli/models.py` matches REST DTO shapes.
   - CLI validation uses the same DTOs or derives from them.

6) **Documentation Reference**
   - REST and TUI docs reference model sources instead of redefining JSON.

## Acceptance Criteria

- REST and WS responses are validated via DTOs at the boundary.
- Core logic uses dataclasses only.
- No REST read endpoint returns aggregate payloads.
- Docs point to the canonical model files.

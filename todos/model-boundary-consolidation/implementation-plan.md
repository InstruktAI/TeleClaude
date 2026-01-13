# Implementation Plan - model-boundary-consolidation

## Overview

Introduce a DTO layer at REST and WebSocket boundaries and remove ad-hoc payload shapes.

## Steps

1) **Inventory Shapes**
   - List current resource shapes across `teleclaude/core/command_handlers.py`,
     `teleclaude/cli/models.py`, and REST/WS handlers.

2) **Define DTOs**
   - Add Pydantic DTOs for REST and WS payloads (resource lists and updates).
   - Keep DTOs aligned with core dataclasses and identifiers.

3) **Add Mappers**
   - Create mapping functions from core dataclasses to DTOs.
   - Centralize any transport-only fields (example `computer`).

4) **Refactor Boundaries**
   - Replace TypedDict response payloads in REST/WS handlers with DTOs.
   - Ensure all REST read endpoints return resource-only payloads.

5) **Align CLI Models**
   - Ensure `teleclaude/cli/models.py` matches DTOs or is replaced by them.
   - Update client validation to use DTOs.

6) **Docs Update**
   - Update REST and TUI docs to point to core models and DTOs as the source of truth.

7) **Tests**
   - Add tests for DTO validation and mapping.
   - Ensure REST and WS responses are validated and stable.

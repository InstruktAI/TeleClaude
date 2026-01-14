# Implementation Plan - model-boundary-consolidation

## Overview
Consolidate resource shapes into a single source of truth and use Pydantic only at system boundaries. Core models will be dataclasses in `teleclaude/core/models.py`, while REST/WS boundaries will use Pydantic DTOs in `teleclaude/adapters/rest_models.py`.

## Proposed Changes

### Group 1: Define DTOs and Mappers
- [x] Define Pydantic DTOs for Sessions, Computers, and Projects in `teleclaude/adapters/rest_models.py`
- [x] Add mapper methods (`from_core`) in DTOs
- [x] Define WebSocket Event DTOs for outgoing WS messages

### Group 2: Refactor REST Adapter Boundaries
- [x] Update `RESTAdapter` list and create endpoints to use DTOs
- [x] Update WebSocket handlers to use DTOs for all outgoing JSON payloads

### Group 3: Align CLI and TUI
- [x] Update `teleclaude/cli/models.py` to use the new DTOs (aliased for compatibility)
- [x] Ensure `TelecAPIClient` leverages Pydantic validation

### Group 4: Documentation and Cleanup
- [x] Update `docs/rest-api.md` with new resource shapes
- [x] Fix `RESTAdapter` event subscription bug (`TeleClaudeEvents.on` -> `self.client.on`)

## Verification Plan

### Automated Tests
- [x] Run existing integration tests: `make test-integration` (Verified E2E boundary integrity)
- [x] Run smoke tests for CLI/TUI: `telec list-sessions`
- [x] Verified full test suite passes: `make test`

### Manual Verification
- [x] Verified TUI session and project trees render correctly with new data shapes

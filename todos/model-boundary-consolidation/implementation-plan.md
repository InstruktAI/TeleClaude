# Implementation Plan - model-boundary-consolidation

## Overview
Consolidate resource shapes into a single source of truth and use Pydantic only at system boundaries. Core models will be dataclasses in `teleclaude/core/models.py`, while REST/WS boundaries will use Pydantic DTOs in `teleclaude/adapters/rest_models.py`.

## User Review Required
> [!IMPORTANT]
> This plan involves refactoring core models which might affect all adapters. Ensure existing tests cover these paths.

## Proposed Changes

### Group 1: Define DTOs and Mappers (Parallelizable)
- [ ] **PARALLEL** Define Pydantic DTOs for Sessions in `teleclaude/adapters/rest_models.py`
  - Create `SessionDTO`, `SessionSummaryDTO`, `CreateSessionResponseDTO`
- [ ] **PARALLEL** Define Pydantic DTOs for Computers and Projects in `teleclaude/adapters/rest_models.py`
  - Create `ComputerDTO`, `ProjectDTO`, `TodoDTO`, `ProjectWithTodosDTO`
- [ ] **PARALLEL** Add mapper functions in `teleclaude/adapters/rest_models.py`
  - Functions to convert from core dataclasses to Pydantic DTOs.
- [ ] **PARALLEL** Define WebSocket Event DTOs in `teleclaude/adapters/rest_models.py`
  - Use these for validating outgoing WS messages.

### Group 2: Refactor REST Adapter Boundaries (Sequential)
- [ ] Update `RESTAdapter.list_sessions` to use `SessionSummaryDTO`
- [ ] Update `RESTAdapter.create_session` to use `CreateSessionResponseDTO`
- [ ] Update `RESTAdapter.list_computers` to use `ComputerDTO`
- [ ] Update `RESTAdapter.list_projects` to use `ProjectDTO`
- [ ] Update `RESTAdapter.list_projects_with_todos` to use `ProjectWithTodosDTO`

### Group 3: Refactor WebSocket Events (Sequential)
- [ ] Update `RESTAdapter._handle_session_updated` and `_handle_session_terminated` to use DTOs
- [ ] Update `RESTAdapter._send_initial_state` to use DTOs
- [ ] Ensure all `send_json` calls in `RESTAdapter` use DTO models

### Group 4: Align CLI and TUI (Sequential)
- [ ] Update `teleclaude/cli/models.py` to use (or match) the new DTOs
- [ ] Refactor `teleclaude/cli/api_client.py` to leverage Pydantic validation if applicable
- [ ] Ensure TUI remains functional with new data shapes

### Group 5: Documentation and Cleanup
- [ ] Update REST API documentation reference to use the new DTOs
- [ ] Remove `asdict_exclude_none` and other serialization hacks if no longer needed

## Verification Plan

### Automated Tests
- [ ] Add unit tests for DTO validation: `tests/unit/test_rest_models.py`
- [ ] Add unit tests for mappers: `tests/unit/test_mappers.py`
- [ ] Run existing integration tests: `make test-integration`
- [ ] Run smoke tests for CLI/TUI: `telec list-sessions`

### Manual Verification
- [ ] Launch daemon and verify `telec list-sessions`
- [ ] Verify TUI session list and project list
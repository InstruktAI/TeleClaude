# Implementation Plan: deployment-cleanup

## Overview

Systematic removal of the manual deploy system. Grep-driven approach: find all
references first, remove in dependency order (consumers before providers), then
update docs.

---

## Phase 1: Core Changes

### Task 1.1: Audit all deploy references

**File(s):** entire codebase

- [x] Grep for: `telec deploy`, `telec deploy`, `deploy_service`,
      `DeployService`, `deploy_status`, `system_status.*deploy`
- [x] Catalog every reference with file path and type (import, handler, test, doc)
- [x] Plan removal order: consumers -> service -> Redis commands -> docs

### Task 1.2: Remove MCP tool and server dispatch

**File(s):** `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp/handlers.py`,
`teleclaude/mcp/role_tools.py`, `teleclaude/mcp_server.py`

- [x] Remove `telec deploy` from `tool_definitions.py` — N/A: MCP module already removed by prior migration
- [x] Remove deploy handler from `handlers.py` — N/A: MCP module already removed
- [x] Remove deploy from `role_tools.py` — N/A: MCP module already removed
- [x] Remove `ToolName.DEPLOY` enum member from `mcp_server.py` — N/A: MCP module already removed
- [x] Remove `_handle_deploy()` inner function from `mcp_server.py` — N/A: MCP module already removed
- [x] Remove deploy entry from dispatch map in `mcp_server.py` — N/A: MCP module already removed
- [x] Update `docs/project/spec/mcp-tool-surface.md` — N/A: file does not exist

Also removed deploy from:

- `teleclaude/cli/telec.py` (DEPLOY enum, CommandDef, dispatch branch, completion)
- `teleclaude/cli/tool_commands.py` (handle_deploy function)
- `teleclaude/api_server.py` (POST /deploy endpoint, CLEARANCE_DEPLOY import, DeployRequest import)
- `teleclaude/api/auth.py` (CLEARANCE_DEPLOY definition)
- `teleclaude/api_models.py` (DeployRequest class)
- `teleclaude/core/tool_activity.py` (deploy entry in activity map)
- `teleclaude/core/tool_access.py` (telec deploy from MEMBER_EXCLUDED and UNAUTHORIZED_EXCLUDED)
- `teleclaude/constants.py` (SystemCommand.DEPLOY, ResultStatus.DEPLOYED)

### Task 1.3: Remove daemon and transport deploy paths

**File(s):** `teleclaude/daemon.py`, `teleclaude/transport/redis_transport.py`,
`teleclaude/core/events.py`, `teleclaude/core/lifecycle.py`

- [x] Remove `DeployService` import and `_handle_deploy()` method from `daemon.py`
- [x] Remove `"deploy"` case from system command dispatch in `daemon.py`
- [x] Remove `DeployArgs` import and deploy arg construction from `redis_transport.py`
- [x] Remove `DeployArgs` dataclass from `core/events.py`
- [x] Remove deploy status check block (~lines 106-130) from `core/lifecycle.py`

### Task 1.4: Remove deploy service

**File(s):** `teleclaude/services/deploy_service.py`

- [x] Delete the file
- [x] Verify no remaining imports of `deploy_service` across codebase

### Task 1.5: Update documentation

**File(s):** docs

- [x] Rewrite `docs/project/procedure/deploy.md` for automated deployment
- [x] Update `docs/project/spec/teleclaude-config.md` with deployment config
- [x] Update `docs/project/design/architecture/system-overview.md` — N/A: no deploy references found
- [x] Write `docs/project/design/architecture/deployment-pipeline.md`
- [x] Update README.md deploy references — N/A: no deploy references found
- [x] Update agent artifacts if they reference deploy — N/A: no deploy references found
- [x] Remove deploy from `docs/project/spec/telec-cli-surface.md`

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Remove or update tests that reference deploy service
  - `tests/unit/test_api_route_auth.py`: removed POST /deploy test case
  - `tests/unit/test_role_tools.py`: updated to use telec agents status instead of telec deploy
  - `tests/unit/test_help_desk_features.py`: removed telec deploy from test data
  - `tests/integration/test_contracts.py`: added deployment to required config keys
- [x] Verify no import errors from removed modules
- [x] Run `make test` — 2349 passed, 106 skipped

### Task 2.2: Quality Checks

- [x] Run `make lint` — passed
- [x] Grep codebase for any remaining deploy references (should be zero outside
      new deployment pipeline code)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — no deferrals

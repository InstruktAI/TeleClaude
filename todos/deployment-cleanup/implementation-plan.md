# Implementation Plan: deployment-cleanup

## Overview

Systematic removal of the manual deploy system. Grep-driven approach: find all
references first, remove in dependency order (consumers before providers), then
update docs.

---

## Phase 1: Core Changes

### Task 1.1: Audit all deploy references

**File(s):** entire codebase

- [ ] Grep for: `telec deploy`, `telec deploy`, `deploy_service`,
      `DeployService`, `deploy_status`, `system_status.*deploy`
- [ ] Catalog every reference with file path and type (import, handler, test, doc)
- [ ] Plan removal order: consumers -> service -> Redis commands -> docs

### Task 1.2: Remove MCP tool and server dispatch

**File(s):** `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp/handlers.py`,
`teleclaude/mcp/role_tools.py`, `teleclaude/mcp_server.py`

- [ ] Remove `telec deploy` from `tool_definitions.py`
- [ ] Remove deploy handler from `handlers.py`
- [ ] Remove deploy from `role_tools.py`
- [ ] Remove `ToolName.DEPLOY` enum member from `mcp_server.py`
- [ ] Remove `_handle_deploy()` inner function from `mcp_server.py`
- [ ] Remove deploy entry from dispatch map in `mcp_server.py`
- [ ] Update `docs/project/spec/mcp-tool-surface.md`

### Task 1.3: Remove daemon and transport deploy paths

**File(s):** `teleclaude/daemon.py`, `teleclaude/transport/redis_transport.py`,
`teleclaude/core/events.py`, `teleclaude/core/lifecycle.py`

- [ ] Remove `DeployService` import and `_handle_deploy()` method from `daemon.py`
- [ ] Remove `"deploy"` case from system command dispatch in `daemon.py`
- [ ] Remove `DeployArgs` import and deploy arg construction from `redis_transport.py`
- [ ] Remove `DeployArgs` dataclass from `core/events.py`
- [ ] Remove deploy status check block (~lines 106-130) from `core/lifecycle.py`

### Task 1.4: Remove deploy service

**File(s):** `teleclaude/services/deploy_service.py`

- [ ] Delete the file
- [ ] Verify no remaining imports of `deploy_service` across codebase

### Task 1.5: Update documentation

**File(s):** docs

- [ ] Rewrite `docs/project/procedure/deploy.md` for automated deployment
- [ ] Update `docs/project/spec/teleclaude-config.md` with deployment config
- [ ] Update `docs/project/design/architecture/system-overview.md`
- [ ] Write `docs/project/design/architecture/deployment-pipeline.md`
- [ ] Update README.md deploy references
- [ ] Update agent artifacts if they reference deploy

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Remove or update tests that reference deploy service
- [ ] Verify no import errors from removed modules
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Grep codebase for any remaining deploy references (should be zero outside
      new deployment pipeline code)
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

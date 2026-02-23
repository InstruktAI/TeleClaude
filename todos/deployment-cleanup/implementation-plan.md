# Implementation Plan: deployment-cleanup

## Overview

Systematic removal of the manual deploy system. Grep-driven approach: find all
references first, remove in dependency order (consumers before providers), then
update docs.

---

## Phase 1: Core Changes

### Task 1.1: Audit all deploy references

**File(s):** entire codebase

- [ ] Grep for: `teleclaude__deploy`, `telec deploy`, `deploy_service`,
      `DeployService`, `deploy_status`, `system_status.*deploy`
- [ ] Catalog every reference with file path and type (import, handler, test, doc)
- [ ] Plan removal order: consumers -> service -> Redis commands -> docs

### Task 1.2: Remove MCP tool

**File(s):** `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp/handlers.py`,
`teleclaude/mcp/role_tools.py`

- [ ] Remove `teleclaude__deploy` from tool definitions
- [ ] Remove deploy handler from handlers.py
- [ ] Remove deploy from role_tools.py
- [ ] Update `docs/project/spec/mcp-tool-surface.md`

### Task 1.3: Remove CLI command

**File(s):** `teleclaude/cli/` (deploy subcommand location)

- [ ] Replace `telec deploy` with a helpful error message:
      "Deployment is now automatic via channels. See: telec version"
- [ ] Or remove the subcommand entirely if the CLI framework shows unknown commands

### Task 1.4: Remove deploy service

**File(s):** `teleclaude/services/deploy_service.py`

- [ ] Delete the file
- [ ] Remove any imports of deploy_service from other modules
- [ ] Remove deploy-related Redis system command handling

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

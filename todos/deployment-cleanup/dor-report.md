# DOR Report: deployment-cleanup

## Assessment Phase: Gate (Final)

## Verdict: PASS (9/10)

All 8 DOR gates satisfied after remediation. Work is ready for build.

## Gate Results

| #   | Gate               | Result         | Evidence                                                                    |
| --- | ------------------ | -------------- | --------------------------------------------------------------------------- |
| 1   | Intent & success   | PASS           | 8 concrete, testable success criteria covering full removal surface         |
| 2   | Scope & size       | PASS           | Systematic deletion + doc updates. Fits single session.                     |
| 3   | Verification       | PASS           | Demo has grep-based validation. Success criteria are binary (exists/not).   |
| 4   | Approach known     | PASS           | All 9 code files enumerated with exact removal targets. Dependency-ordered. |
| 5   | Research           | AUTO-SATISFIED | No third-party dependencies.                                                |
| 6   | Dependencies       | PASS           | After `deployment-auto-update`. Roadmap dependency set.                     |
| 7   | Integration safety | PASS           | Pure removal. Rollback = revert commit.                                     |
| 8   | Tooling impact     | AUTO-SATISFIED | No scaffolding changes.                                                     |

## Plan-to-Requirement Fidelity

All plan tasks trace to requirements. No contradictions. No orphan tasks.

- Requirement 1 (MCP tool removal) → Task 1.2: covers tool_definitions, handlers, role_tools, mcp_server
- Requirement 2 (deploy dispatch paths) → Task 1.3: covers daemon, transport, events, lifecycle
- Requirement 3 (deploy_service deletion) → Task 1.4: delete file
- Requirement 4 (DeployArgs removal) → Task 1.3: explicit item
- Requirement 5 (lifecycle cleanup) → Task 1.3: explicit item
- Requirement 6-7 (docs) → Task 1.5: doc updates + new pipeline doc
- Requirement 8 (lint/test) → Task 2.1-2.2: validation phase

## Verified File Inventory

**Code (9 files):**

| File                                      | What to remove                                                      |
| ----------------------------------------- | ------------------------------------------------------------------- |
| `teleclaude/mcp/tool_definitions.py`      | `teleclaude__deploy` tool definition                                |
| `teleclaude/mcp/handlers.py`              | Deploy handler method                                               |
| `teleclaude/mcp/role_tools.py`            | Deploy in exclusion lists                                           |
| `teleclaude/mcp_server.py`                | `ToolName.DEPLOY` enum, `_handle_deploy()`, dispatch entry          |
| `teleclaude/services/deploy_service.py`   | Delete entire file                                                  |
| `teleclaude/daemon.py`                    | `DeployService` import, `_handle_deploy()`, deploy command dispatch |
| `teleclaude/core/events.py`               | `DeployArgs` dataclass                                              |
| `teleclaude/core/lifecycle.py`            | Deploy status check on startup (~lines 106-130)                     |
| `teleclaude/transport/redis_transport.py` | `DeployArgs` import, deploy arg construction                        |

**Tests (3 files):**

| File                                    | What to update                     |
| --------------------------------------- | ---------------------------------- |
| `tests/unit/test_role_tools.py`         | Deploy in test fixtures            |
| `tests/unit/test_help_desk_features.py` | Deploy in test fixtures            |
| `tests/unit/test_verify_deploy.py`      | Tests for `tools/verify_deploy.py` |

**Tools (assess during build):**

- `tools/verify_deploy.py` — may be repurposed or removed

**Docs (update/create):**

- `docs/project/spec/mcp-tool-surface.md` — remove deploy tool entry
- `docs/project/procedure/deploy.md` — rewrite for automated flow
- `docs/project/design/architecture/system-overview.md` — update
- `docs/project/spec/teleclaude-config.md` — add deployment channel config
- `README.md` — remove deploy references
- `docs/project/design/architecture/deployment-pipeline.md` — new

## Actions Taken (Gate Phase)

### Initial gate (score 7)

- Full codebase grep discovered 5 code files missing from plan
- Confirmed `telec deploy` CLI subcommand does NOT exist (deploy is MCP-only)
- Cataloged complete file inventory

### Remediation (score 7 → 9)

- Updated requirements: replaced phantom `telec deploy` CLI references with accurate removal targets
- Updated plan Task 1.2: added `mcp_server.py` with 3 specific removal items
- Rewrote plan Task 1.3: now covers daemon, transport, events, lifecycle (4 files, 5 removal items)
- Simplified plan Task 1.4: focused on file deletion + import verification
- Updated success criteria to reflect full removal surface (8 items)

## Blockers

None.

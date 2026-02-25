# Review Findings: mcp-migration-delete-mcp

## Critical

- None.

## Important

- `docs/project/index.yaml:1`, `docs/project/index.yaml:2`, `docs/third-party/index.yaml:1` — regenerated index roots are pinned to this temporary worktree (`~/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-delete-mcp/...`). `teleclaude/context_selector.py:268`-`teleclaude/context_selector.py:293` resolves relative snippet paths against `payload.project_root`, so once this worktree is removed the selector will resolve to nonexistent paths and skip snippet content in Phase 2. Regenerate indexes with the canonical repo root path before merge.

## Suggestions

- `docs/project/index.yaml:459` still describes AI-to-AI operations as using “TeleClaude MCP tools.” Consider a follow-up docs sync to align remaining snippet descriptions with tool/API terminology.

## Fixes Applied

- Issue: `docs/project/index.yaml:1`, `docs/project/index.yaml:2`, `docs/third-party/index.yaml:1` used worktree-rooted paths that break Phase 2 snippet loading after worktree removal.
  Fix: Repointed index roots to the canonical repository path (`~/Workspace/InstruktAI/TeleClaude`) so `context_selector` resolves snippet files against stable paths.
  Commit: `56d31371852aa933232176c3417b49a3d506721b`

## Manual Verification Evidence

- Targeted regression checks:
  - `pytest -q tests/unit/test_daemon.py tests/unit/test_lifecycle.py tests/unit/test_models.py tests/unit/test_adapter_client.py tests/unit/test_role_tools.py tests/unit/test_help_desk_features.py tests/unit/test_command_mapper.py tests/integration/test_contracts.py`
  - Result: `130 passed`.
- Lint/type checks:
  - `make lint`
  - Result: passed (`ruff check` clean, `pyright` 0 errors/warnings).
- Runtime checks (`make status`, `make restart`) were executed but are environment-dependent for host service wiring and were not used as acceptance evidence for this worktree review.

## Paradigm-Fit Assessment

- Data flow: MCP runtime paths were removed from daemon/core lifecycle, and role-based tool filtering remains in core (`teleclaude/core/tool_access.py`) rather than adapters.
- Component reuse: Existing command-handler and permission-matrix patterns were reused; no copy-paste fork patterns were introduced.
- Pattern consistency: Transport boundary cleanup follows existing core/adapters separation, with no new adapter leaks into core modules.

## Verdict

REQUEST CHANGES

# Review Findings: mcp-migration-telec-commands

## Critical

1. Role enforcement is bypassable on legacy endpoints that the new CLI still uses.
   - Evidence:
     - `Depends(CLEARANCE_...)` is present for new routes only (`/sessions/run`, `/sessions/{id}/unsubscribe`, `/sessions/{id}/result`, `/sessions/{id}/widget`, `/sessions/{id}/escalate`, `/agents/{agent}/status`, `/deploy`) in [teleclaude/api_server.py:853](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:853), [teleclaude/api_server.py:901](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:901), [teleclaude/api_server.py:919](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:919), [teleclaude/api_server.py:972](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:972), [teleclaude/api_server.py:1043](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1043), [teleclaude/api_server.py:1262](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1262), [teleclaude/api_server.py:1298](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1298).
     - Core legacy endpoints have no clearance dependency (`/sessions`, `/sessions` POST, `/sessions/{id}` DELETE, `/sessions/{id}/message`, `/sessions/{id}/file`, `/computers`, `/projects`, `/agents/availability`) at [teleclaude/api_server.py:369](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:369), [teleclaude/api_server.py:419](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:419), [teleclaude/api_server.py:568](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:568), [teleclaude/api_server.py:591](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:591), [teleclaude/api_server.py:672](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:672), [teleclaude/api_server.py:1092](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1092), [teleclaude/api_server.py:1128](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1128), [teleclaude/api_server.py:1210](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1210).
     - Channel routes are also unauthenticated in [teleclaude/channels/api_routes.py:46](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/channels/api_routes.py:46) and [teleclaude/channels/api_routes.py:55](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/channels/api_routes.py:55).
     - Existing access check explicitly bypasses controls when identity headers are absent in [teleclaude/api/session_access.py:30](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/session_access.py:30).
   - Impact: The stated requirement “every API endpoint checks caller system/human role” is not met, and blocked actions remain callable through legacy paths.

2. System-role enforcement still depends on a writable role marker file, not a tamper-resistant server authority.
   - Evidence:
     - API auth reads system role from `~/.teleclaude/tmp/sessions/{id}/teleclaude_role` in [teleclaude/api/auth.py:46](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/auth.py:46).
     - Wrapper writes the same marker in [teleclaude/entrypoints/mcp_wrapper.py:261](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/entrypoints/mcp_wrapper.py:261).
     - If marker read fails, auth falls back to `None` role in [teleclaude/api/auth.py:58](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/auth.py:58), then uses wrapper denylist logic via `get_excluded_tools(...)` at [teleclaude/api/auth.py:116](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/auth.py:116).
   - Impact: This does not satisfy the stated replacement of file-based filtering with tamper-resistant daemon-side enforcement, and leaves a privilege-escalation path if marker state is altered.

## Important

1. `--help` output does not provide the required rich behavioral guidance/examples; `telec docs --help` also misses two-phase guidance.
   - Evidence:
     - Help is intercepted before command handlers by `_maybe_show_help(...)` in [teleclaude/cli/telec.py:482](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:482) and [teleclaude/cli/telec.py:856](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:856), so handler docstring examples are not shown.
     - `docs` command surface has no notes for phase-1/phase-2 usage in [teleclaude/cli/telec.py:268](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:268).
     - Manual check: `.venv/bin/python -m teleclaude.cli.telec sessions run --help` and `.venv/bin/python -m teleclaude.cli.telec docs --help` showed only usage/options, not behavioral guidance/examples.
   - Impact: Core help-text acceptance criteria are not met.

2. `sessions list` behavior and help text disagree; current implementation returns global sessions by default.
   - Evidence:
     - Help states default is “spawned by current” in [teleclaude/cli/tool_commands.py:98](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/tool_commands.py:98).
     - Implementation sends plain `GET /sessions` without caller filtering in [teleclaude/cli/tool_commands.py:107](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/tool_commands.py:107) and [teleclaude/cli/tool_commands.py:114](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/tool_commands.py:114).
   - Impact: Misleading operator behavior and unnecessary session exposure.

3. New auth/endpoint behavior is largely untested.
   - Evidence:
     - No tests found targeting `teleclaude/api/auth.py`, `verify_caller`, or new tool routes (`/sessions/run`, `/sessions/{id}/unsubscribe`, `/sessions/{id}/result`, `/sessions/{id}/widget`, `/sessions/{id}/escalate`, `/todos/*`, `/deploy`, `/agents/{agent}/status`) in the changed test set.
   - Impact: High-risk security and boundary behavior lacks regression protection.

## Suggestions

1. Return a 400-class error for unknown agent names in `/agents/{agent}/status` by converting `ValueError` from `normalize_agent_name(...)` to `HTTPException(400)` at [teleclaude/api_server.py:1275](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1275).

2. Consider failing unknown removed aliases (`telec list`, `telec claude`, `telec gemini`, `telec codex`) with explicit non-zero “unknown command” instead of silent exit, currently reachable via [teleclaude/cli/telec.py:761](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:761).

## Paradigm-Fit Assessment

- Data flow: The PR keeps HTTP boundary translation in adapter/CLI layers, but the role model still leaks legacy wrapper/file-based policy into core API authorization.
- Component reuse: Good reuse of shared `tool_api_call()` and `CommandMapper`, but help-generation architecture now suppresses per-command rich guidance.
- Pattern consistency: New endpoint patterns are consistent, yet security is inconsistent across adjacent routes (new routes protected, legacy routes unprotected).

## Manual Verification Evidence

- Executed:
  - `.venv/bin/python -m teleclaude.cli.telec --help`
  - `.venv/bin/python -m teleclaude.cli.telec sessions --help`
  - `.venv/bin/python -m teleclaude.cli.telec sessions run --help`
  - `.venv/bin/python -m teleclaude.cli.telec todo --help`
  - `.venv/bin/python -m teleclaude.cli.telec docs --help`
- Targeted tests run:
  - `pytest -q tests/unit/test_telec_cli.py`
  - `pytest -q tests/unit/test_install_hooks.py`
  - `pytest -q tests/unit/test_diagram_extractors.py`
  - `pytest -q tests/unit/test_next_machine_demo.py`
  - `pytest -q tests/integration/test_e2e_smoke.py`
  - `pytest -q tests/integration/test_multi_adapter_broadcasting.py`
  - `pytest -q tests/integration/test_state_machine_workflow.py`

## Verdict

REQUEST CHANGES

## Fixes Applied

- Issue: Critical 1 - role enforcement bypass on legacy/channel endpoints.
  Fix: Added clearance dependencies to legacy API routes (`/sessions`, `/sessions/{id}` delete/message/file, `/computers`, `/projects`, `/agents/availability`) and channel routes (`/api/channels/*`), with web-header identity support in `verify_caller`.
  Commit: `5193e8ca`

- Issue: Critical 2 - system-role trust based on writable marker files.
  Fix: Replaced marker-file role lookup with daemon-owned session-state derivation (`session_metadata.system_role` with `working_slug` worker fallback) in API auth.
  Commit: `0528126d`

- Issue: Important 1 - `--help` lacks behavioral guidance and docs two-phase usage.
  Fix: Added schema-driven notes/examples for `sessions run --help` and explicit phase-1/phase-2 guidance for `docs --help`, with integration coverage.
  Commit: `3f0d9b2b`

- Issue: Important 2 - `sessions list` default behavior mismatched help text.
  Fix: Updated `/sessions` to default-filter by caller-spawned sessions when `x-caller-session-id` is present, and honor `?all=true` for global visibility; added unit tests for both paths.
  Commit: `dc8c30fc`

- Issue: Important 3 - insufficient auth/endpoint regression tests.
  Fix: Added targeted unit tests for `verify_caller` identity and role derivation, plus route-level authorization tests across protected legacy and new tool endpoints.
  Commit: `309ca78f`

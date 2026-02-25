# Review Findings: mcp-migration-telec-commands

## Critical

1. **R1-F1 — Role enforcement is still bypassable on multiple session endpoints, including `telec sessions tail`.**
   - Evidence:
     - These routes do not require any `CLEARANCE_*` dependency:
       [teleclaude/api_server.py:636](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:636),
       [teleclaude/api_server.py:663](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:663),
       [teleclaude/api_server.py:724](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:724),
       [teleclaude/api_server.py:756](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:756),
       [teleclaude/api_server.py:795](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:795).
     - These handlers rely on `check_session_access(...)`, which explicitly allows access when web identity headers are absent:
       [teleclaude/api/session_access.py:33](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/session_access.py:33).
     - Authorization tests cover only a subset of routes and omit these endpoints:
       [tests/unit/test_api_route_auth.py:25](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/tests/unit/test_api_route_auth.py:25).
   - Impact: caller role checks are incomplete; transcript reads and session-control operations can bypass the new clearance layer.

2. **R1-F2 — The new route-level authorization gates regress TUI behavior.**
   - Evidence:
     - `GET /sessions`, `GET /computers`, `GET /projects`, and `GET /agents/availability` now require clearance:
       [teleclaude/api_server.py:377](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:377),
       [teleclaude/api_server.py:1114](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1114),
       [teleclaude/api_server.py:1152](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1152),
       [teleclaude/api_server.py:1235](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1235).
     - `TelecAPIClient` does not send identity headers on requests:
       [teleclaude/cli/api_client.py:85](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/api_client.py:85),
       [teleclaude/cli/api_client.py:280](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/api_client.py:280).
     - TUI startup refresh depends on those endpoints:
       [teleclaude/cli/tui/app.py:272](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/tui/app.py:272).
   - Impact: TUI data refresh now receives 401s and fails to hydrate core views, violating the non-regression constraint.

3. **R1-F3 — Dual-factor identity is bypassable via web headers over Unix socket.**
   - Evidence:
     - `verify_caller(...)` accepts `x-web-user-email`/`x-web-user-role` and skips `X-Caller-Session-Id` entirely:
       [teleclaude/api/auth.py:81](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api/auth.py:81).
     - Middleware treats Unix-socket requests (`request.client is None`) as trusted for those headers:
       [teleclaude/api_server.py:347](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:347).
   - Impact: a local caller can present forged web-role headers and bypass the session-id/tmux verification path, conflicting with the tamper-resistant enforcement goal and the `no session_id -> 401` acceptance criterion.

## Important

1. **R1-F4 — `sessions run` does not persist caller linkage, so default caller-scoped listing can hide newly created run sessions.**
   - Evidence:
     - `run_session(...)` ignores `identity` and creates metadata without `initiator_session_id`:
       [teleclaude/api_server.py:876](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:876),
       [teleclaude/api_server.py:897](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:897).
     - `create_session(...)` does inject `initiator_session_id`, but only on that path:
       [teleclaude/api_server.py:460](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:460).
     - Caller-scoped session listing depends on `initiator_session_id`:
       [teleclaude/api_server.py:421](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:421).
   - Impact: user-visible behavior is inconsistent between `sessions start` and `sessions run`.

2. **R1-F5 — Help-text acceptance criteria remain incomplete for many subcommands.**
   - Evidence:
     - Leaf help only includes guidance/examples when `sub.notes` is populated:
       [teleclaude/cli/telec.py:611](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:611).
     - Multiple subcommands define flags but no notes/examples (for example `sessions start`, `todo prepare`, `channels publish`):
       [teleclaude/cli/telec.py:120](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:120),
       [teleclaude/cli/telec.py:321](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:321),
       [teleclaude/cli/telec.py:246](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:246).
     - Manual checks confirm those help outputs show usage/options only.
   - Impact: requirement “every subcommand help has behavioral guidance and examples covering parameters/input shapes” is not yet satisfied.

## Suggestions

1. Convert `normalize_agent_name(...)` `ValueError` to `HTTPException(400)` in
   [teleclaude/api_server.py:1302](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/api_server.py:1302)
   so invalid agent values do not surface as 500s.

2. Either implement `--closed` behavior end-to-end or remove the flag from CLI surface/help:
   [teleclaude/cli/telec.py:117](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands/teleclaude/cli/telec.py:117).

## Paradigm-Fit Assessment

- Data flow: adapter/core boundary intent is improved, but several legacy session routes still bypass the same clearance pathway used by new routes.
- Component reuse: good reuse of `tool_api_call()` and central CLI surface, but authorization and identity handling are inconsistent across API clients (`tool_client` vs `api_client`).
- Pattern consistency: adjacent session endpoints now use mixed security patterns (clearance dependencies vs `check_session_access` bypass), creating non-uniform trust boundaries.

## Manual Verification Evidence

- Targeted tests run:
  - `pytest -q tests/unit/test_api_auth.py tests/unit/test_api_route_auth.py tests/unit/test_api_server.py::test_list_sessions_defaults_to_caller_spawned_only tests/unit/test_api_server.py::test_list_sessions_all_flag_disables_caller_filter tests/integration/test_telec_cli_commands.py::test_sessions_run_help_includes_behavior_and_example tests/integration/test_telec_cli_commands.py::test_docs_help_includes_two_phase_guidance`
- Manual CLI help checks:
  - `.venv/bin/python -m teleclaude.cli.telec sessions start --help`
  - `.venv/bin/python -m teleclaude.cli.telec sessions run --help`
  - `.venv/bin/python -m teleclaude.cli.telec todo prepare --help`
  - `.venv/bin/python -m teleclaude.cli.telec channels publish --help`
- Additional verification:
  - Confirmed via local UDS probe that Unix-socket requests expose `request.client` as `None`, which satisfies the middleware “trusted” condition for web identity headers.

## Fixes Applied

- **R1-F1**
  - Fix: Added clearance dependencies to uncovered session endpoints (`keys`, `voice`, `agent-restart`, `revive`, `messages`) and extended route-auth coverage for these paths.
  - Commit: `8c38dd28`
- **R1-F2**
  - Fix: Updated `TelecAPIClient` to send caller identity headers (`x-caller-session-id`, `x-tmux-session`) on daemon API requests; added unit coverage for header propagation.
  - Commit: `6fba42fe`
- **R1-F3**
  - Fix: Enforced `X-Caller-Session-Id` requirement in `verify_caller` and tightened identity-header middleware trust to loopback TCP hosts only.
  - Commit: `ae6dd4d9`
- **R1-F4**
  - Fix: Added `initiator_session_id` propagation for `sessions run` via channel metadata and covered linkage with a focused API server unit test.
  - Commit: `d09ad75b`
- **R1-F5**
  - Fix: Added generated behavioral notes/examples for all help leaves (subcommands + top-level leaf commands) and added tests enforcing Notes/Examples presence.
  - Commit: `ed04c453`

## Verdict

REQUEST CHANGES

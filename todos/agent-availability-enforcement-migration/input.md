# Input: agent-availability-enforcement-migration

## User Intent

- Investigate and fix regression where unavailable agents are still selected/launched.
- Ensure all agent selection and startup flows go through one availability-aware helper route.
- Produce a thorough, implementation-ready migration todo with concrete call sites.

## Verified Regression Evidence

- Date: 2026-02-26
- `telec agents availability` showed `claude` unavailable (`unavailable_until=2026-02-26T19:00:00Z`).
- Sessions still launched with Claude:
  - explicit: `telec sessions run ... --agent claude`
  - implicit default: `telec sessions run ...` (no `--agent`)
- Daemon logs showed `agent_then_message: agent=claude` and launcher command execution for Claude during the unavailable window.

## Root Cause Summary

- Runtime availability helper exists in `teleclaude/helpers/agent_cli.py::_pick_agent`.
- That helper is only used by `run_once` and `run_job`.
- Session/worker launch surfaces mostly enforce only `enabled` policy (`assert_agent_enabled`, `get_enabled_agents`) or use hardcoded/default Claude.

## Migration Scope

1. Establish one canonical routable-agent policy:
   - enabled check
   - availability check
   - degraded behavior policy (decide once, apply everywhere)
2. Apply policy to all runtime launch and restart paths.
3. Remove enabled-only default/fallback selection from call sites that create or start sessions.
4. Add regression tests across API, daemon, adapters, cron, and CLI scaffolding paths.
5. Add observability so rejected launches are visible in logs with source path.

## Confirmed Call Sites To Migrate

### API server

- `teleclaude/api_server.py`
  - `/sessions` uses enabled-only resolver (`_resolve_enabled_agent`)
  - `/sessions/run` uses enabled-only validation/default

### Command handlers / daemon execution layer

- `teleclaude/core/command_handlers.py`
  - `start_agent`
  - `resume_agent`
  - `agent_restart`
  - `run_agent_command`
- `teleclaude/daemon.py`
  - auto-command path for `agent` and `agent_then_message`

### Mapper defaults

- `teleclaude/core/command_mapper.py`
  - `_default_agent_name` uses first enabled agent only

### Adapters and launcher surfaces

- `teleclaude/adapters/discord_adapter.py`
  - enabled-only agent pool and default
  - hardcoded `auto_command="agent claude"` paths
  - launcher path `auto_command=f"agent {agent_name}"` from enabled list
- `teleclaude/adapters/telegram_adapter.py`
  - hardcoded `auto_command="agent claude"` paths
- `teleclaude/adapters/telegram/callback_handlers.py`
  - callback mappings hardcode agent auto-commands
- `teleclaude/hooks/whatsapp_handler.py`
  - hardcoded `auto_command="agent claude"`

### Automation / cron / CLI scaffolding

- `teleclaude/cron/runner.py`
  - `agent = config.agent or "claude"`
- `teleclaude/cli/telec.py`
  - bug scaffold dispatch pins `agent="claude"`

## Expected Deliverables

- Canonical helper in core for routable-agent resolution and validation.
- All launch/restart call sites migrated to helper.
- No hardcoded runtime agent defaults that bypass availability policy.
- Regression tests proving unavailable agents cannot be selected/launched from any entrypoint above.
- Short runbook/log query to verify enforcement in production.

## Open Policy Decision (Must Be Settled Early)

- Degraded status semantics:
  - option A: blocked for all auto/default selection, manual explicit allowed
  - option B: blocked for all selection
  - option C: treated as available

Pick one and codify in helper + tests to remove current inconsistencies.

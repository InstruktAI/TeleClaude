---
description: 'Operational runbooks for diagnosing and recovering TeleClaude incidents.'
id: 'project/procedure/troubleshooting'
scope: 'project'
type: 'procedure'
---

# Troubleshooting Runbooks — Procedure

## Purpose

Give operators short, direct playbooks for common incidents.

Use this when something is broken now and you need a safe recovery path.

## Allowed control commands

Use only:

- `make status`
- `make restart`
- `instrukt-ai-logs teleclaude --since <window> [--grep <text>]`

If restart is not enough, use:

- `make stop`
- `make start`

## Universal first-response sequence

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m`
3. Identify symptom in runbooks below.
4. Follow that runbook exactly.
5. Verify recovery with `make status` and fresh logs.

## Runbook: MCP tools time out or fail

### Symptom

- MCP tool calls hang, time out, or return backend unavailable errors.

### Likely causes

- MCP socket unhealthy or restarting repeatedly.
- Wrapper reconnecting but backend not stabilizing.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "mcp|socket|restart|health"`

### Recover

1. `make restart`
2. Wait for readiness.
3. Re-check MCP logs for repeated restart loops.

### Verify

- MCP calls complete normally.
- No repeating MCP health-check failures in last 2 minutes.

## Runbook: Session output is frozen/stale

### Symptom

- Session is running but output in UI stops updating.

### Likely causes

- Poller watch loop failed.
- Poller not aligned with tmux session state.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "poller|output|tmux|watch"`

### Recover

1. `make restart`
2. Re-open affected session and confirm output starts moving.

### Verify

- New output events appear.
- No poller watch errors in recent logs.

## Runbook: Agent finished but no notification/summary

### Symptom

- Agent turn ends, but no stop notification, summary, or downstream update appears.

### Likely causes

- Hook outbox backlog.
- Hook event processing failures.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "hook|outbox|agent_stop|dispatch|retry"`

### Recover

1. `make restart`
2. Watch logs for outbox processing resuming.

### Verify

- Delayed notifications/summaries appear.
- Hook dispatch errors stop repeating.

## Runbook: Headless session cannot be recovered

### Symptom

- Headless session exists, but transcript retrieval/resume fails.

### Likely causes

- Missing native transcript path.
- Native identity not mapped correctly.

### Fast checks

1. `instrukt-ai-logs teleclaude --since 5m --grep "headless|native_session_id|native_log_file|session_map"`
2. Confirm latest hook events carried native identity fields.

### Recover

1. Restart daemon if mapping updates were not applied.
2. Re-trigger hook flow from source session.

### Verify

- Session now has native identity fields populated.
- Session data retrieval works.

## Runbook: Cleanup is not happening (old sessions/artifacts pile up)

### Symptom

- Old sessions remain open forever.
- Orphan tmux/workspace artifacts accumulate.

### Likely causes

- Periodic cleanup loop failed.
- Cleanup errors repeating each cycle.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 10m --grep "cleanup|inactive_72h|orphan|workspace|voice"`

### Recover

1. `make restart`
2. Wait one cleanup cycle window for normal behavior.

### Verify

- Cleanup logs show successful pass.
- Orphan artifacts no longer increase.

## Runbook: API appears unhealthy

### Symptom

- API-backed tools or TUI calls fail unexpectedly.

### Likely causes

- API interface startup/runtime failure.
- Daemon not healthy overall.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "api|socket|bind|watch|error"`

### Recover

1. `make restart`
2. If restart fails, run `make stop` then `make start`.

### Verify

- `make status` reports healthy.
- Recent logs show normal API startup without repeated failures.

## Runbook: API restart churn (SIGTERM storm)

### Symptom

- API socket repeatedly disappears/rebinds.
- MCP/API clients show bursts of connection-refused errors.
- Logs show frequent `Received SIGTERM signal...`.

### Likely causes

- External restart trigger loop (automation/operator flow repeatedly issuing restarts).
- Checkpoint-driven housekeeping loops forcing repeated daemon restarts.
- Less likely: internal daemon crash (verify via logs before assuming this).

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 30m --grep "Received SIGTERM signal"`
3. `instrukt-ai-logs teleclaude --since 30m --grep "Removing API server socket|Connection refused"`
4. `instrukt-ai-logs teleclaude --since 30m --grep "API server task crashed|API server task exited unexpectedly"`

### Recover

1. Stop issuing additional restart commands.
2. Perform one controlled restart: `make restart`.
3. If `make restart` reports timeout/degraded, do not immediately chain another restart; check logs for ongoing startup first:
   `instrukt-ai-logs teleclaude --since 2m --grep "Starting TeleClaude daemon|API server listening on /tmp/teleclaude-api.sock"`
4. Validate once: `make status`.
5. Monitor for 10 minutes and confirm SIGTERM events do not continue repeating.

### Verify

- No new `Received SIGTERM signal...` lines in the verification window.
- No sustained connection-refused bursts in MCP/API logs.
- API socket remains present and healthy in `make status`.

## Incident Trail For Next AI

When an incident is non-trivial, preserve the reasoning trail in two places:

1. **Operational runbook context**: this file (`docs/project/procedure/troubleshooting.md`) for stable symptom/recovery steps.
2. **Case trail with timeline + hypotheses**: append to `docs/explore/teleclaude-api-socket-degradation.md`.

Minimum fields for each case-trail entry:

- timestamp window
- symptom
- evidence (exact commands/log patterns)
- root-cause hypothesis + confidence
- change/prototype attempted
- verification result
- next decision

## Escalate when

Escalate immediately if any of the following persists after one controlled restart:

- MCP restart storm continues.
- Hook outbox remains blocked.
- Poller output remains frozen.
- Daemon repeatedly exits during startup.

When escalating, include:

- Exact symptom
- Time window
- Commands run
- Relevant log excerpts from `instrukt-ai-logs`

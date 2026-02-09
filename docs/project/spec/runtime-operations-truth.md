---
id: 'project/spec/runtime-operations-truth'
type: 'spec'
scope: 'project'
description: 'Operational source of truth for daemon background operations, impact, and recovery.'
---

# Runtime Operations Truth — Spec

## Why this exists

When TeleClaude feels "weird" (slow output, missing hooks, dead MCP calls), the root cause is usually one background operation that stopped, lagged, or got stuck.

This document is the single operational truth for what runs, how often, what breaks when it fails, and how to recover fast.

## Read this first during incidents

1. Identify the user-visible symptom.
2. Find the matching operation in the table below.
3. Run the "first checks" exactly as written.
4. If needed, recover with `make restart` and verify with `make status`.

## Background operations matrix

| Operation                            | Run frequency     | What it does                                                                                                      | What users notice if it fails                                                          | Self-recovery                             | First checks                                                                                     |
| ------------------------------------ | ----------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Hook outbox worker                   | Every 1 second    | Pulls pending hook events from `hook_outbox`, dispatches them, marks delivered or reschedules retries             | Session summaries delayed, stop notifications delayed, hook-driven updates appear late | Partial (retries continue if loop alive)  | Check daemon log for hook dispatch failures; check for growing undelivered outbox rows           |
| MCP socket watcher                   | Every 2 seconds   | Health-checks MCP socket and restarts MCP server when unhealthy                                                   | MCP tools time out or fail intermittently                                              | Yes (bounded restart attempts per window) | Check daemon log for repeated MCP health failures/restarts; verify `/tmp/teleclaude.sock` exists |
| Poller watch loop                    | Every 5 seconds   | Keeps output pollers aligned with active tmux sessions and recreates missing pollers                              | Session output appears frozen or stale                                                 | Yes (next watch cycle attempts repair)    | Check daemon log for poller watch errors; confirm tmux session exists and is alive               |
| Resource monitor                     | Every 60 seconds  | Writes runtime resource snapshots to logs                                                                         | No direct user error, but incidents become harder to debug                             | Yes                                       | Check monitoring logs for missing resource snapshots                                             |
| WAL checkpoint loop                  | Every 300 seconds | Checkpoints SQLite WAL to control disk growth                                                                     | Gradual performance degradation, bigger WAL files                                      | Yes                                       | Check daemon log for WAL checkpoint failures                                                     |
| Launchd watch loop (macOS, optional) | Every 300 seconds | Logs launchd service state transitions for observability                                                          | No direct user symptom; missing launchd diagnostics                                    | Yes                                       | Check whether launchd watch is enabled and writing entries                                       |
| Periodic cleanup loop                | Every 1 hour      | Cleans inactive sessions (72h), orphan tmux sessions, orphan workspaces, orphan wrappers, stale voice assignments | Old/stale sessions pile up, leftover artifacts remain                                  | Yes (next cycle)                          | Check daemon log for periodic cleanup errors and orphan cleanup failures                         |

## Command pipeline operations (not timer loops)

| Operation             | Trigger                  | What it does                                         | Failure symptom                               | First checks                                                                        |
| --------------------- | ------------------------ | ---------------------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------- |
| Command queue worker  | New command persisted    | Executes session/message/control commands from queue | Commands appear accepted but do nothing       | Check daemon log around command handler errors; verify DB writes and queue progress |
| Session launcher      | Session creation command | Creates tmux session and writes session metadata     | New session fails to start or starts half-way | Check tmux creation errors and session metadata updates                             |
| Hook receiver enqueue | Agent hook invocation    | Normalizes hook payload and inserts outbox row       | Hook event lost before daemon sees it         | Check receiver logs; confirm event type is in forwarding allowlist                  |

## Failure impact by symptom

| Symptom                                    | Most likely operation                          |
| ------------------------------------------ | ---------------------------------------------- |
| "MCP tools hang"                           | MCP socket watcher or MCP server restart churn |
| "No new output in running session"         | Poller watch loop / poller alignment           |
| "Agent finished but no notification"       | Hook outbox worker                             |
| "Summaries/TTS lag badly"                  | Hook outbox worker backlog                     |
| "Daemon feels fine but disk keeps growing" | WAL checkpoint loop                            |
| "Old dead sessions never disappear"        | Periodic cleanup loop                          |

## Fast recovery sequence

Run these in order:

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m`
3. If unhealthy: `make restart`
4. `make status` again
5. `instrukt-ai-logs teleclaude --since 2m --grep "error|warning|hook|mcp|poller|cleanup"`

## What this spec guarantees

- Operation names map to real runtime tasks.
- Frequencies reflect current default runtime settings.
- Recovery instructions use approved service-control commands.

If code changes operation names, intervals, or ownership, this file must be updated in the same change.

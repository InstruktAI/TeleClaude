---
id: architecture/session-lifecycle
description: How TeleClaude creates, runs, and cleans up tmux-backed sessions.
type: architecture
scope: project
requires:
  - database.md
  - tmux-management.md
  - output-polling.md
  - adapter-client.md
---

# Session Lifecycle

## Purpose
- Manage tmux-backed sessions from creation through cleanup and stale recovery.

## Inputs/Outputs
- Inputs: CreateSessionCommand, tmux status, adapter events, poller exit events.
- Outputs: DB session rows, tmux sessions, UI channels, session summaries.

## Invariants
- Session IDs are UUIDs; tmux session names are prefixed with `tc_`.
- Working directory must exist and be absolute; invalid paths fail session creation.
- DB session rows are created before channels/topics so metadata can be persisted.
- Cleanup removes listeners and workspace output directory; closed sessions are marked in DB.

## Primary Flows
- Create: validate working dir → create DB session → create UI channel/topic → start tmux session → start polling.
- Update: session field changes trigger title updates and cache refreshes.
- Close: terminate tmux (if needed) → delete channels/topics → mark closed or delete DB row.
- Stale cleanup: if tmux session is missing, terminate session and remove DB row.

## Failure Modes
- External tmux termination triggers cleanup and closed session marking.
- Race conditions for very new sessions are guarded (skip stale cleanup for young sessions).

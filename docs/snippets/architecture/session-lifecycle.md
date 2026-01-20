---
id: teleclaude/architecture/session-lifecycle
type: architecture
scope: project
description: Session creation, agent launch, message handling, and cleanup lifecycle.
requires:
  - database.md
  - tmux-management.md
  - output-polling.md
  - adapter-client.md
---

Purpose
- Describe how TeleClaude creates, runs, and tears down sessions.

Primary flows
- Create session: allocate session_id, tmux session, and DB record.
- Optional agent launch: inject agent command and update session metadata.
- Message handling: send keys to tmux and start output polling.
- Cleanup: terminate tmux and mark session closed, removing listeners.

Invariants
- session_id is generated once and returned immediately.
- tmux session names use a stable prefix with the session_id.
- Closed sessions stop polling and are removed from cache snapshots.

Failure modes
- Invalid working directories prevent session creation.
- Missing tmux sessions trigger cleanup and session termination.

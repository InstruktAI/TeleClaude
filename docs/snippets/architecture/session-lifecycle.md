---
id: architecture/session-lifecycle
type: architecture
scope: project
description: Complete lifecycle of a terminal session from creation to cleanup.
---

# Session Lifecycle

## 1. Creation
- **Ingress**: A `/new-session` command arrives via an adapter.
- **Queueing**: Command is persisted in the SQLite queue.
- **Execution**: The `SessionLauncher` starts a new `tmux` session.
- **Persistence**: Session metadata is saved in the `sessions` table.
- **Announcement**: The originating adapter announces the session (e.g., creates a Telegram topic).

## 2. Active Operation
- **Input**: Commands are sent to the `tmux` pane via `tmux_io`.
- **Output**: The `OutputPoller` reads from `tmux` and emits `OutputEvent`s.
- **Summarization**: Periodic AI-summarization updates the Telegram topic.
- **Clutter Control**: User inputs and feedback are cleaned up based on session state.

## 3. Termination
- **Close Command**: User calls `/close-session` or AI calls `end_session`.
- **Cleanup**:
  - `tmux` process is killed.
  - SQLite record is marked as closed.
  - Final summary is posted.
  - Topic is archived or marked inactive.

## Invariants
- `session_id` is stable throughout the lifecycle.
- `tmux` session name format: `tc_{session_id[:8]}`.
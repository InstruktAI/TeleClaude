# TerminalAdapter Requirements

## Goal
Make non-tmux terminal sessions first-class TeleClaude sessions so hook-driven agent CLIs can receive listener notifications, without requiring TELECLAUDE_SESSION_ID up front.

## Core Principles
- TerminalAdapter is NOT a UI adapter and does not implement send_feedback.
- Terminal delivery is centralized: all terminal injection (tmux + TTY) routes through TerminalAdapter.
- Hooks remain the inbound channel for agent CLIs; no new UI surface is required for TerminalAdapter.
- Creation/attachment must be robust and idempotent across repeated hooks.
- Session origin is always tracked via origin_adapter (existing adapter keys like telegram/redis, plus terminal).
- TerminalAdapter is a one-way delivery sink only (not part of broadcasting or UI mirroring).

## Scope
- Create/attach TeleClaude sessions on-the-fly when hooks arrive without TELECLAUDE_SESSION_ID.
- Register a terminal identity (TTY + PID + cwd + agent metadata) for those sessions.
- Preserve existing tmux session lifecycle for TeleClaude-created sessions.

## Non-Goals
- No TUI control API (no send_feedback).
- No terminal output capture beyond existing hooks/transcripts.
- No change to agent CLI hook protocols beyond optional metadata (TTY/PID).

## Session Identity
- Primary identity: controlling TTY path (e.g., /dev/ttys007).
- PID is liveness-only and must never be used as primary identity.
- Multiple hooks from the same TTY should resolve to the same TeleClaude session.

## Data Model
- Use origin_adapter as the source indicator (existing adapter keys like telegram/redis, plus terminal).
- Persist terminal metadata:
  - native_tty_path
  - native_pid
  - cwd
  - active_agent
  - native_session_id (if provided by agent)

## Behavior Requirements
1. Hook intake without TELECLAUDE_SESSION_ID:
   - Resolve terminal identity via TTY.
   - If session exists for that TTY, attach.
   - Else create a new TeleClaude session with origin_adapter=terminal.
   - Set origin_adapter=terminal.

2. Hook intake with TELECLAUDE_SESSION_ID:
   - Use existing session record (TeleClaude-managed session).
   - Do NOT update terminal metadata when origin_adapter is not terminal.

3. TerminalAdapter delivery:
   - Route all injection through TerminalAdapter.
   - Delivery order: tmux (if exists) -> TTY fallback (if TTY+PID valid).
   - Never auto-create tmux for terminal sessions.

4. Listener notifications:
   - Must use TerminalAdapter for all terminal injection.
   - Behavior should be identical for tmux vs terminal sessions.

5. Broadcasting:
   - TerminalAdapter does not participate in broadcasting or UI mirroring.

## Safety / Constraints
- Only write to a TTY when it exists and PID is alive.
- Never assume TELECLAUDE_SESSION_ID exists for hook-based events.
- Keep tmux lifecycle management in terminal_bridge; do not move it into TerminalAdapter.

## Integration Points
- hooks/receiver: capture TTY/PID/cwd from caller context.
- hooks/receiver: create/attach sessions for no-TELECLAUDE_SESSION_ID hooks.
- AdapterClient: register TerminalAdapter for routing outbound notifications.
- agent_coordinator + daemon listener flows: replace direct tmux send-keys with TerminalAdapter send.

## Open Decisions
- Where to store terminal metadata (sessions table vs UX state only).

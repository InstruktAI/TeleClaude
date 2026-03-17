# Bug: Telegram-initiated session starts but does not deliver the user's initial message to the agent

## Symptom

Telegram-initiated session starts but does not deliver the user's initial message to the agent

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

Traced the full message delivery chain for Telegram private chat sessions:

1. `_handle_private_text` in `private_handlers.py` creates a new session when none exists
2. Session is created with `auto_command="agent {default_agent}"` which starts the agent CLI
3. The user's message is separately enqueued via `process_message` → inbound queue
4. The inbound queue worker waits for the session to exit "initializing" state (startup gate)
5. Bootstrap task creates tmux, dispatches auto_command to tmux, then transitions to "active"
6. Startup gate passes → message is injected into tmux via `send_keys`

The problem: step 6 happens immediately after step 5, but the agent CLI started in step 5 hasn't
finished TUI initialization yet. The message keystrokes are sent to the tmux PTY while the agent
TUI is still setting up (raw mode, alternate screen, etc.), causing the input to be lost.

Compared with the API session creation flow (`sessions_actions_routes.py` line 443) which uses
`agent_then_message` auto_command — this bundles the message into the auto_command and uses
`_handle_agent_then_message` in `daemon_session.py` which:

- Starts the agent
- Waits for TUI output to stabilize (quiet period after startup banner)
- Verifies agent process is running
- Only then injects the message with bracketed paste

The private chat handler was missing this stabilization step.

## Root Cause

Race condition between agent TUI initialization and message injection. The inbound queue waits
only for the session to exit "initializing" (which happens right after the auto_command is
dispatched to tmux), not for the agent to actually be ready to accept input. The
`agent_then_message` auto_command mechanism solves this with output stabilization, but the
private chat handler was using plain `agent` auto_command + separate `process_message` instead.

## Fix Applied

Changed `_handle_private_text` in `private_handlers.py` to use `agent_then_message` auto_command
(with `shlex.quote` for safe text embedding) when creating a new session, matching the pattern
used by the API session creation flow. The user's message is now bundled into the auto_command
and delivered through the `_handle_agent_then_message` pipeline which waits for agent TUI
stabilization before injecting.

For existing sessions, message delivery continues through the inbound queue (unchanged).

# Input: help-desk-startup-command-ordering

## Problem

Help-desk sessions are created and a tmux pane appears, but the first customer
message can arrive before auto-start fully settles. In that window, the first
message interleaves with the startup command, so no valid agent turn is produced.

## Evidence

1. Session creation path sets `auto_command` for help-desk sessions:
   - `teleclaude/adapters/discord_adapter.py` (`_create_session_for_message`)
2. Session launcher queues bootstrap asynchronously and returns immediately:
   - `teleclaude/core/session_launcher.py` (`_create_session_with_intent`)
3. Bootstrap currently marks session `active` before running auto-command:
   - `teleclaude/daemon.py` (`_bootstrap_session_resources`)
4. Message dispatch sends text to tmux immediately (default `send_enter=True`):
   - `teleclaude/core/command_handlers.py` (`process_message`)
   - `teleclaude/core/tmux_io.py` (`process_text`)

Observed sequence from runtime logs for session `e189e31a`:

1. `Created session ... auto_command=agent claude`
2. `Message for session e189e31a: Hi...`
3. `agent_start: session=e189e31a ...`

Live tmux capture showed command contamination (`--model opusHi`), confirming the
first user message appended into the startup command line.

## Root Cause Snapshot

This is an ordering race, not a missing auto-command:

- auto-command is queued and does execute,
- but first inbound `process_message` can run during `initializing` bootstrap,
- resulting in command-line interleaving inside the same tmux pane.

## Desired Outcome

- First customer message is never injected into tmux until startup bootstrap
  completes its auto-command dispatch attempt.
- Session leaves `initializing` only after startup command dispatch is complete.
- If startup takes too long or fails, behavior is explicit and observable (no
  silent loss, no silent no-op).

## Constraints

- Preserve adapter boundaries (no Discord-specific logic inside core tmux logic).
- Keep change scope atomic to startup ordering and first-message safety.
- Avoid host-level service operations; validation uses logs/tests only.

## Non-Goals

- No redesign of all session lifecycle states.
- No changes to unrelated adapter routing logic.
- No broad tmux transport rewrite.

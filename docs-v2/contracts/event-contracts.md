# Event Contracts

## session_created
Session record + tmux name assigned (may still be initializing).

## agent_ready
Agent command injected and stabilized.

## task_delivered
Initial task injected after agent ready.

## agent_resumed
Resume command injected.

## agent_restarted
Restart command injected.

## command_delivered
Agent CLI command injected (no guarantee of completion).

## message_delivered
Free‑form message injected.

## session_closed
Session cleanup completed and session marked closed.

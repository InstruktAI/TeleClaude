# Event Contracts

## session_created
Session record + tmux name assigned (may still be initializing).

## agent_ready
Agent command injected and stabilized.

## task_started
Initial task injected after agent ready.

## agent_resumed
Resume command injected.

## agent_restarted
Restart command injected.

## agent_command_delivered
Agent CLI command injected (no guarantee of completion).

## message_delivered
Free‑form message injected.

## session_ended
Session cleanup completed.

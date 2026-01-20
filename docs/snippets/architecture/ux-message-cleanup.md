---
id: architecture/ux-message-cleanup
description: Ephemeral message cleanup using pending_message_deletions for clean UI history.
type: architecture
scope: project
requires:
  - database.md
---

# UX Message Cleanup

## Purpose
- Keep UI threads clean by deleting ephemeral messages on defined triggers.

## Inputs/Outputs
- Inputs: send_message calls with cleanup_trigger/ephemeral flags; user input events.
- Outputs: delete_message calls and pending_message_deletions rows.

## Invariants
- Feedback messages are deleted before sending the next feedback message.
- User input messages are deleted on the next user input.
- Persistent messages (ephemeral=False) are never tracked for deletion.

## Primary Flows
- AdapterClient.send_message tracks ephemerals in pending_message_deletions.
- Telegram UI pre-handler deletes pending user_input messages and clears the queue.
- Feedback cleanup deletes pending feedback messages before new feedback is sent.

## Failure Modes
- Deletion failures are logged and treated as best-effort; queues are still cleared.

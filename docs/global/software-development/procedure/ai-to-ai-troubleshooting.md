---
description: 'Identify and fix common issues with AI-to-AI coordination, timeouts, and notifications.'
id: 'software-development/procedure/ai-to-ai-troubleshooting'
scope: 'domain'
type: 'procedure'
---

# AI-to-AI Troubleshooting — Procedure

## Goal

Diagnose and resolve failures in AI-to-AI session dispatch and notifications.

## Preconditions

- An AI-to-AI session has been dispatched via `teleclaude__run_agent_command`.
- Access to daemon logs (`bin/telec logs`).
- SQLite3 CLI installed for database verification.

## Steps

1.  **Identify Failures:** Check the Initiator's terminal for timeout errors or missing worker stop notifications.
2.  **Verify Dispatch:** Check the daemon logs for `Listener register attempt` to confirm the Initiator was correctly registered as a listener.
3.  **Inspect Database:**
    ```bash
    sqlite3 teleclaude.db "SELECT session_id, initiator_session_id, active_agent, lifecycle_status FROM session WHERE initiator_session_id IS NOT NULL"
    ```
    Confirm the `initiator_session_id` matches the parent session.
4.  **Analyze Timeouts:** If receiving `TeleClaude backend did not respond in time`, verify the `ThinkingMode` is valid and the database is not saturated.
5.  **Check Tmux Connectivity:** Ensure the `deliver_listener_message` is not failing due to an invalid or closed tmux session.

## Outputs

- Corrected session configuration or recovered notification flow.
- Verified worker session state in the database.

## Recovery

- **Handshake Failures:** If `handshake replay failed`, manually retry the command or restart the client session.
- **Missing Notifications:** Manually check worker status with `teleclaude__get_session_data` if the automated notification fails to deliver.
- **Dead Listeners:** Restart the TeleClaude daemon if in-memory listeners have been cleared due to an unplanned restart.

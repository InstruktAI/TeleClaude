---
description: 'Identify and fix common issues with AI-to-AI coordination, timeouts, and notifications.'
id: 'general/procedure/ai-to-ai-troubleshooting'
scope: 'global'
type: 'procedure'
visibility: 'public'
---

# AI-to-AI Troubleshooting — Procedure

## Goal

Diagnose and resolve failures in AI-to-AI session dispatch and notifications.

## Preconditions

- An AI-to-AI session has been dispatched via `telec sessions run` or `telec sessions start`.
- Access to daemon logs (`bin/telec logs` or equivalent).
- SQLite3 CLI installed for database verification.

## Steps

1. **Identify Failures:** Check the Initiator's terminal for timeout errors or missing worker stop notifications.
2. **Verify Dispatch:** Check the daemon logs for `Registered listener` to confirm the Initiator was correctly registered as a listener for the Worker.
3. **Inspect Database:**
   ```bash
   sqlite3 ~/.teleclaude/teleclaude.db \
     "SELECT session_id, initiator_session_id, active_agent, lifecycle_status \
        FROM sessions WHERE initiator_session_id IS NOT NULL"
   ```
   Confirm the `initiator_session_id` matches the parent session.
4. **Inspect Listener Rows:**
   ```bash
   sqlite3 ~/.teleclaude/teleclaude.db \
     "SELECT target_session_id, caller_session_id, one_shot, registered_at \
        FROM session_listeners"
   ```
   Confirm a row exists for the (Initiator → Worker) pair. Persistent listeners have `one_shot=0`; one-shot have `one_shot=1`.
5. **Check for Active Direct Link (Suppression Diagnostic):** If notifications stopped arriving while you were in a direct conversation with the same target, this is expected suppression — not a bug. Check for an active link:
   ```bash
   sqlite3 ~/.teleclaude/teleclaude.db \
     "SELECT link_id, mode, severed_at FROM conversation_links \
        WHERE severed_at IS NULL"
   ```
   If a `direct_link` row exists with both Initiator and Worker as members (check `conversation_link_members`), the listener is suppressed by design. Close the link to resume delivery: `telec sessions send <target> --close-link`, or use `telec sessions unsubscribe <target>` to drop both axes at once.
6. **Analyze Timeouts:** If receiving `TeleClaude backend did not respond in time`, verify the `ThinkingMode` is valid and the database is not saturated.
7. **Check Tmux Connectivity:** Ensure `deliver_listener_message` is not failing due to an invalid or closed tmux session.

## Outputs

- Corrected session configuration or recovered notification flow.
- Verified worker session state and listener subscription state in the database.

## Recovery

- **Handshake Failures:** If `handshake replay failed`, manually retry the command or restart the client session.
- **Missing Notifications:** Manually check worker status with `telec sessions tail <worker_session_id> --thinking --tools` if the automated notification fails to deliver.
- **`unsubscribe` returned `success` with all flags false:** No subscription existed for that pair — this is the idempotent empty-state success, not an error.
- **Unexpected notification silence while in a direct conversation:** Expected behavior. Suppression resumes delivery when the link is severed.

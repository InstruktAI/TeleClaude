"""Migrate ux_state JSON blob to proper columns."""

# mypy: disable-error-code="misc"

import json

import aiosqlite


async def migrate(db: aiosqlite.Connection) -> None:
    """Migrate ux_state JSON blob to columns.

    Migrates:
    - Scalar fields from ux_state JSON → session columns
    - pending_deletions list → pending_message_deletions table (deletion_type='user_input')
    - pending_feedback_deletions list → pending_message_deletions table (deletion_type='feedback')
    """
    # Fetch all sessions with ux_state
    cursor = await db.execute("SELECT session_id, ux_state FROM sessions WHERE ux_state IS NOT NULL")
    rows = await cursor.fetchall()

    for row in rows:
        session_id = row[0]
        ux_state_raw = row[1]

        if not ux_state_raw:
            continue

        try:
            ux = json.loads(ux_state_raw)
        except json.JSONDecodeError:
            continue

        # Update scalar columns
        await db.execute(
            """
            UPDATE sessions SET
                output_message_id = ?,
                last_input_adapter = ?,
                notification_sent = ?,
                native_session_id = ?,
                native_log_file = ?,
                active_agent = ?,
                thinking_mode = ?,
                native_tty_path = ?,
                tmux_tty_path = ?,
                native_pid = ?,
                tui_log_file = ?,
                tui_capture_started = ?
            WHERE session_id = ?
        """,
            (
                ux.get("output_message_id"),
                ux.get("last_input_adapter"),
                1 if ux.get("notification_sent") else 0,
                ux.get("native_session_id"),
                ux.get("native_log_file"),
                ux.get("active_agent"),
                ux.get("thinking_mode"),
                ux.get("native_tty_path"),
                ux.get("tmux_tty_path"),
                ux.get("native_pid"),
                ux.get("tui_log_file"),
                1 if ux.get("tui_capture_started") else 0,
                session_id,
            ),
        )

        # Migrate pending_deletions list
        for msg_id in ux.get("pending_deletions", []):
            await db.execute(
                """
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'user_input')
            """,
                (session_id, msg_id),
            )

        # Migrate pending_feedback_deletions list
        for msg_id in ux.get("pending_feedback_deletions", []):
            await db.execute(
                """
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'feedback')
            """,
                (session_id, msg_id),
            )

    await db.commit()

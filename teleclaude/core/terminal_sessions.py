"""Terminal-origin session registration helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from teleclaude.config import config
from teleclaude.core.models import SessionAdapterMetadata
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.ux_state import SessionUXState, UXStatePayload


def terminal_tmux_name(tty_path: str) -> str:
    """Build a stable tmux session sentinel for terminal-origin sessions."""
    digest = hashlib.sha256(tty_path.encode("utf-8")).hexdigest()[:16]
    return f"terminal:{digest}"


def terminal_tmux_name_for_session(session_id: str) -> str:
    """Build a TeleClaude-owned tmux session name for a terminal-origin session."""
    return f"tc_term_{session_id[:8]}"


def _merge_ux_state(existing: SessionUXState, incoming: SessionUXState) -> SessionUXState:
    merged = SessionUXState.from_dict(cast(UXStatePayload, existing.to_dict()))
    if incoming.active_agent is not None:
        merged.active_agent = incoming.active_agent
    if incoming.native_pid is not None:
        merged.native_pid = incoming.native_pid
    merged.native_tty_path = incoming.native_tty_path
    merged.tmux_tty_path = incoming.tmux_tty_path
    merged.tui_log_file = incoming.tui_log_file
    merged.tui_capture_started = incoming.tui_capture_started
    return merged


def ensure_terminal_session(
    tty_path: str,
    parent_pid: int | None,
    agent: str | None,
    cwd: str,
) -> str:
    """Create or attach a terminal-origin session based on TTY."""
    db_path = config.database.path
    now = datetime.now(timezone.utc).isoformat()
    title = f"[{config.computer.name}] Terminal ({Path(tty_path).name})"
    session_id = str(uuid.uuid4())

    output_file = get_output_file(session_id)
    ux_state = SessionUXState(
        active_agent=agent,
        native_tty_path=tty_path,
        native_pid=parent_pid,
        tui_log_file=str(output_file),
        tui_capture_started=False,
    )
    ux_state_json = json.dumps(ux_state.to_dict())
    adapter_metadata = SessionAdapterMetadata().to_json()

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        cursor = conn.execute(
            """
            SELECT session_id, ux_state, closed
            FROM sessions
            WHERE origin_adapter = 'terminal'
              AND json_extract(ux_state, '$.native_tty_path') = ?
            """,
            (tty_path,),
        )
        row = cast(tuple[object, object, object] | None, cursor.fetchone())
        if row:
            existing_id = str(row[0])
            existing_state_raw = row[1]
            existing_closed = bool(row[2])

            if not existing_closed:
                existing_state = SessionUXState()
                try:
                    if isinstance(existing_state_raw, str) and existing_state_raw:
                        parsed_raw: object = json.loads(existing_state_raw)
                        if isinstance(parsed_raw, dict):
                            existing_state = SessionUXState.from_dict(cast(UXStatePayload, parsed_raw))
                except json.JSONDecodeError:
                    existing_state = SessionUXState()

                merged_state = _merge_ux_state(existing_state, ux_state)
                if not merged_state.tui_log_file:
                    merged_state.tui_log_file = str(get_output_file(existing_id))
                tmux_name = terminal_tmux_name_for_session(existing_id)
                conn.execute(
                    """
                    UPDATE sessions
                    SET ux_state = ?, last_activity = ?, working_directory = ?, closed = 0, tmux_session_name = ?
                    WHERE session_id = ?
                    """,
                    (json.dumps(merged_state.to_dict()), now, cwd or "~", tmux_name, existing_id),
                )
                conn.commit()
                return existing_id
            # Session was marked closed in legacy data; remove it and create a fresh session.
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (existing_id,),
            )
            conn.commit()

        tmux_name = terminal_tmux_name_for_session(session_id)
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                origin_adapter, adapter_metadata, closed, created_at,
                last_activity, terminal_size, working_directory, description, ux_state
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                config.computer.name,
                title,
                tmux_name,
                "terminal",
                adapter_metadata,
                now,
                now,
                "160x80",
                cwd or "~",
                "Terminal-origin session",
                ux_state_json,
            ),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()

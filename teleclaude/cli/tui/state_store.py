"""Persistence helpers for TUI state."""

from __future__ import annotations

import json
import os

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.state import DocStickyInfo, PreviewState, TuiState
from teleclaude.cli.tui.types import StickySessionInfo
from teleclaude.paths import TUI_STATE_PATH

logger = get_logger(__name__)


def load_sticky_state(state: TuiState) -> None:
    """Load sticky session/doc state from ~/.teleclaude/tui_state.json."""
    if not TUI_STATE_PATH.exists():
        logger.debug("No TUI state file found, starting with empty sticky state")
        return

    try:
        with open(TUI_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)

        sticky_data = data.get("sticky_sessions", [])
        state.sessions.sticky_sessions = [StickySessionInfo(session_id=item["session_id"]) for item in sticky_data]

        sticky_docs = data.get("sticky_docs", [])
        state.preparation.sticky_previews = [
            DocStickyInfo(
                doc_id=item["doc_id"],
                command=item["command"],
                title=item.get("title", ""),
            )
            for item in sticky_docs
        ]
        expanded_todos = data.get("expanded_todos", [])
        if isinstance(expanded_todos, list):
            state.preparation.expanded_todos = set(str(item) for item in expanded_todos)

        input_highlights = data.get("input_highlights", [])
        if isinstance(input_highlights, list):
            state.sessions.input_highlights = set(str(item) for item in input_highlights)

        output_highlights = data.get("output_highlights", [])
        if isinstance(output_highlights, list):
            state.sessions.output_highlights = set(str(item) for item in output_highlights)

        last_summary = data.get("last_summary", {})
        if isinstance(last_summary, dict):
            state.sessions.last_summary = {
                str(session_id): str(summary)
                for session_id, summary in last_summary.items()
                if isinstance(session_id, str) and isinstance(summary, str)
            }

        collapsed_sessions = data.get("collapsed_sessions", [])
        if isinstance(collapsed_sessions, list):
            state.sessions.collapsed_sessions = set(str(item) for item in collapsed_sessions)

        preview_data = data.get("preview")
        if isinstance(preview_data, dict) and preview_data.get("session_id"):
            state.sessions.preview = PreviewState(session_id=preview_data["session_id"])

        logger.info(
            "Loaded TUI state: %d sticky, %d docs, %d in_hl, %d out_hl, %d summaries, %d collapsed, preview=%s",
            len(state.sessions.sticky_sessions),
            len(state.preparation.sticky_previews),
            len(state.sessions.input_highlights),
            len(state.sessions.output_highlights),
            len(state.sessions.last_summary),
            len(state.sessions.collapsed_sessions),
            state.sessions.preview.session_id[:8] if state.sessions.preview else None,
        )
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
        logger.warning("Failed to load TUI state from %s: %s", TUI_STATE_PATH, e)
        state.sessions.sticky_sessions = []
        state.preparation.sticky_previews = []


def save_sticky_state(state: TuiState) -> None:
    """Save sticky session/doc state to ~/.teleclaude/tui_state.json.

    Uses atomic replacement and advisory locking to prevent race conditions.
    """
    try:
        TUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        preview = state.sessions.preview
        state_data = {
            "sticky_sessions": [{"session_id": s.session_id} for s in state.sessions.sticky_sessions],
            "sticky_docs": [
                {"doc_id": d.doc_id, "command": d.command, "title": d.title} for d in state.preparation.sticky_previews
            ],
            "expanded_todos": sorted(state.preparation.expanded_todos),
            "input_highlights": sorted(state.sessions.input_highlights),
            "output_highlights": sorted(state.sessions.output_highlights),
            "last_summary": dict(sorted(state.sessions.last_summary.items())),
            "collapsed_sessions": sorted(state.sessions.collapsed_sessions),
            "preview": {"session_id": preview.session_id} if preview else None,
        }

        # Atomic write with lock to prevent race conditions
        lock_path = TUI_STATE_PATH.with_suffix(".lock")
        try:
            # Use a lock file to serialize writes
            with open(lock_path, "w", encoding="utf-8") as lock_file:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass  # fcntl not available or locking failed, proceed best-effort

                # Write to temp file then atomic replace
                tmp_path = TUI_STATE_PATH.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, TUI_STATE_PATH)

        except (OSError, IOError) as e:
            logger.error("Failed to atomic save TUI state: %s", e)
            return  # Skip write rather than risk corruption

        logger.debug(
            "Saved %d sticky sessions, %d sticky docs, %d expanded todos to %s",
            len(state.sessions.sticky_sessions),
            len(state.preparation.sticky_previews),
            len(state.preparation.expanded_todos),
            TUI_STATE_PATH,
        )
    except (OSError, IOError) as e:
        logger.error("Failed to save TUI state to %s: %s", TUI_STATE_PATH, e)

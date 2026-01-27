"""Persistence helpers for TUI state."""

from __future__ import annotations

import json

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.state import DocStickyInfo, StickySessionInfo, TuiState
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
        state.sessions.sticky_sessions = [
            StickySessionInfo(session_id=item["session_id"], show_child=item.get("show_child", True))
            for item in sticky_data
        ]

        sticky_docs = data.get("sticky_docs", [])
        state.preparation.sticky_previews = [
            DocStickyInfo(
                doc_id=item["doc_id"],
                command=item["command"],
                title=item.get("title", ""),
            )
            for item in sticky_docs
        ]

        logger.info(
            "Loaded %d sticky sessions, %d sticky docs from %s",
            len(state.sessions.sticky_sessions),
            len(state.preparation.sticky_previews),
            TUI_STATE_PATH,
        )
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
        logger.warning("Failed to load TUI state from %s: %s", TUI_STATE_PATH, e)
        state.sessions.sticky_sessions = []
        state.preparation.sticky_previews = []


def save_sticky_state(state: TuiState) -> None:
    """Save sticky session/doc state to ~/.teleclaude/tui_state.json."""
    try:
        TUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        state_data = {
            "sticky_sessions": [
                {"session_id": s.session_id, "show_child": s.show_child} for s in state.sessions.sticky_sessions
            ],
            "sticky_docs": [
                {"doc_id": d.doc_id, "command": d.command, "title": d.title} for d in state.preparation.sticky_previews
            ],
        }

        with open(TUI_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

        logger.debug(
            "Saved %d sticky sessions, %d sticky docs to %s",
            len(state.sessions.sticky_sessions),
            len(state.preparation.sticky_previews),
            TUI_STATE_PATH,
        )
    except (OSError, IOError) as e:
        logger.error("Failed to save TUI state to %s: %s", TUI_STATE_PATH, e)

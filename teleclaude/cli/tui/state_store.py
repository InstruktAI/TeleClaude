"""Persistence helpers for TUI state.

Adapted for Textual reactive model: loads/saves from distributed view state
instead of a centralized TuiState object.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from instrukt_ai_logging import get_logger

from teleclaude.paths import TUI_STATE_PATH

logger = get_logger(__name__)


@dataclass
class PersistedState:
    """Flat container for state loaded from disk."""

    sticky_session_ids: list[str] = field(default_factory=list)
    expanded_todos: set[str] = field(default_factory=set)
    input_highlights: set[str] = field(default_factory=set)
    output_highlights: set[str] = field(default_factory=set)
    # session_id → {"text": str, "ts": float (monotonic epoch)}
    last_output_summary: dict[str, dict[str, object]] = field(default_factory=dict)  # guard: loose-dict
    collapsed_sessions: set[str] = field(default_factory=set)
    preview_session_id: str | None = None
    animation_mode: str = "periodic"
    pane_theming_mode: str = "full"


def load_state() -> PersistedState:
    """Load persisted TUI state from ~/.teleclaude/tui_state.json."""
    state = PersistedState()

    if not TUI_STATE_PATH.exists():
        logger.debug("No TUI state file found, starting fresh")
        return state

    try:
        with open(TUI_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)

        sticky_data = data.get("sticky_sessions", [])
        state.sticky_session_ids = [item["session_id"] for item in sticky_data if isinstance(item, dict)]

        expanded_todos = data.get("expanded_todos", [])
        if isinstance(expanded_todos, list):
            state.expanded_todos = set(str(item) for item in expanded_todos)

        input_highlights = data.get("input_highlights", [])
        if isinstance(input_highlights, list):
            state.input_highlights = set(str(item) for item in input_highlights)

        output_highlights = data.get("output_highlights", [])
        if isinstance(output_highlights, list):
            state.output_highlights = set(str(item) for item in output_highlights)

        last_output_summary = data.get("last_output_summary", {})
        if isinstance(last_output_summary, dict):
            parsed: dict[str, dict[str, object]] = {}  # guard: loose-dict
            for k, v in last_output_summary.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, dict) and "text" in v:
                    parsed[k] = v
                elif isinstance(v, str):
                    # Backward compat: old format was just a string
                    parsed[k] = {"text": v, "ts": 0.0}
            state.last_output_summary = parsed

        collapsed_sessions = data.get("collapsed_sessions", [])
        if isinstance(collapsed_sessions, list):
            state.collapsed_sessions = set(str(item) for item in collapsed_sessions)

        preview_data = data.get("preview")
        if isinstance(preview_data, dict) and preview_data.get("session_id"):
            state.preview_session_id = preview_data["session_id"]

        anim_mode = data.get("animation_mode", "periodic")
        if anim_mode in ("off", "periodic", "party"):
            state.animation_mode = anim_mode

        pane_mode = data.get("pane_theming_mode", "full")
        if isinstance(pane_mode, str) and pane_mode:
            state.pane_theming_mode = pane_mode

        logger.info(
            "Loaded TUI state: %d sticky, %d in_hl, %d out_hl, preview=%s, anim=%s",
            len(state.sticky_session_ids),
            len(state.input_highlights),
            len(state.output_highlights),
            state.preview_session_id[:8] if state.preview_session_id else None,
            state.animation_mode,
        )
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
        logger.warning("Failed to load TUI state from %s: %s", TUI_STATE_PATH, e)

    return state


def save_state(
    *,
    sessions_state: dict[str, object] | None = None,  # guard: loose-dict
    preparation_state: dict[str, object] | None = None,  # guard: loose-dict
    animation_mode: str = "periodic",
    pane_theming_mode: str = "full",
) -> None:
    """Save TUI state to ~/.teleclaude/tui_state.json.

    Accepts state dicts from each view's get_persisted_state() method.
    """
    sessions = sessions_state or {}
    prep = preparation_state or {}

    state_data = {
        "sticky_sessions": sessions.get("sticky_sessions", []),
        "expanded_todos": prep.get("expanded_todos", []),
        "input_highlights": sessions.get("input_highlights", []),
        "output_highlights": sessions.get("output_highlights", []),
        "last_output_summary": sessions.get("last_output_summary", {}),
        "collapsed_sessions": sessions.get("collapsed_sessions", []),
        "preview": sessions.get("preview"),
        "animation_mode": animation_mode,
        "pane_theming_mode": pane_theming_mode,
    }

    try:
        TUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        lock_path = TUI_STATE_PATH.with_suffix(".lock")
        try:
            with open(lock_path, "w", encoding="utf-8") as lock_file:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass

                tmp_path = TUI_STATE_PATH.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, TUI_STATE_PATH)

        except (OSError, IOError) as e:
            logger.error("Failed to atomic save TUI state: %s", e)
            return

        logger.debug("Saved TUI state to %s", TUI_STATE_PATH)
    except (OSError, IOError) as e:
        logger.error("Failed to save TUI state to %s: %s", TUI_STATE_PATH, e)


# --- Legacy compatibility stub (old controller.py still imports this) ---
# Delete when Phase 4 cleanup removes old curses code.
def save_sticky_state(_state: object) -> None:
    pass

"""Persistence helpers for Textual TUI state."""

from __future__ import annotations

import json
import os
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.paths import TUI_STATE_PATH

logger = get_logger(__name__)

_REQUIRED_NAMESPACES = ("sessions", "preparation", "status_bar", "app")
_FLAT_FORMAT_KEYS = (
    "sticky_sessions",
    "expanded_todos",
    "input_highlights",
    "output_highlights",
    "last_output_summary",
    "collapsed_sessions",
    "preview",
    "animation_mode",
    "pane_theming_mode",
)


def _normalize_animation_mode(value: object) -> str:
    if isinstance(value, str) and value in {"off", "periodic", "party"}:
        return value
    return "periodic"


def _normalize_pane_theming_mode(value: object) -> str:
    from teleclaude.cli.tui.theme import normalize_pane_theming_mode

    if not isinstance(value, str):
        return "agent_plus"
    try:
        return normalize_pane_theming_mode(value)
    except ValueError:
        return "agent_plus"


def _is_flat_state(data: dict[str, object]) -> bool:  # guard: loose-dict - persisted JSON payload
    return "sticky_sessions" in data or any(key in data for key in _FLAT_FORMAT_KEYS)


def _migrate_flat_state(data: dict[str, object]) -> dict[str, dict[str, object]]:  # guard: loose-dict
    sessions: dict[str, object] = {}  # guard: loose-dict - dynamic session state payload
    for key in (
        "sticky_sessions",
        "input_highlights",
        "output_highlights",
        "last_output_summary",
        "collapsed_sessions",
        "preview",
    ):
        if key in data:
            sessions[key] = data[key]

    preparation: dict[str, object] = {}  # guard: loose-dict - dynamic preparation state payload
    if "expanded_todos" in data:
        preparation["expanded_todos"] = data["expanded_todos"]

    status_bar: dict[str, object] = {  # guard: loose-dict - dynamic footer state payload
        "animation_mode": _normalize_animation_mode(data.get("animation_mode")),
        "pane_theming_mode": _normalize_pane_theming_mode(data.get("pane_theming_mode")),
    }

    return {
        "sessions": sessions,
        "preparation": preparation,
        "status_bar": status_bar,
        "app": {},
    }


def _empty_state() -> dict[str, dict[str, object]]:  # guard: loose-dict - namespaced state payload
    return {key: {} for key in _REQUIRED_NAMESPACES}


def _normalize_namespaced_state(data: dict[str, object]) -> dict[str, dict[str, object]]:  # guard: loose-dict
    state: dict[str, dict[str, object]] = {}  # guard: loose-dict - namespaced state payload
    for key, value in data.items():
        if isinstance(value, dict):
            state[key] = value
    for key in _REQUIRED_NAMESPACES:
        state.setdefault(key, {})
    return state


def _jsonify(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, set):
        return [_jsonify(item) for item in sorted(value, key=str)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def load_state() -> dict[str, dict[str, object]]:  # guard: loose-dict - namespaced state payload
    """Load persisted TUI state from ~/.teleclaude/tui_state.json."""
    if not TUI_STATE_PATH.exists():
        logger.debug("No TUI state file found, starting fresh")
        return _empty_state()

    try:
        with open(TUI_STATE_PATH, encoding="utf-8") as file:
            loaded: Any = json.load(file)
        if not isinstance(loaded, dict):
            logger.warning("TUI state at %s is not an object; ignoring", TUI_STATE_PATH)
            return _empty_state()

        raw = dict(loaded)
        if _is_flat_state(raw):
            state = _migrate_flat_state(raw)
            logger.info("Migrated flat TUI state to namespaced format")
            return state
        return _normalize_namespaced_state(raw)
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        logger.warning("Failed to load TUI state from %s: %s", TUI_STATE_PATH, exc)
        return _empty_state()


def save_state(state: dict[str, object]) -> None:  # guard: loose-dict - namespaced state payload
    """Save namespaced TUI state to ~/.teleclaude/tui_state.json."""
    payload: dict[str, object] = {}  # guard: loose-dict - namespaced state payload
    for key, value in state.items():
        if isinstance(value, dict):
            payload[key] = _jsonify(value)
    for key in _REQUIRED_NAMESPACES:
        payload.setdefault(key, {})

    try:
        TUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_path = TUI_STATE_PATH.with_suffix(".lock")
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass

            tmp_path = TUI_STATE_PATH.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, TUI_STATE_PATH)
        logger.debug("Saved TUI state to %s", TUI_STATE_PATH)
    except OSError as exc:
        logger.error("Failed to save TUI state to %s: %s", TUI_STATE_PATH, exc)


# --- Legacy compatibility stub (old controller.py still imports this) ---
def save_sticky_state(_state: object) -> None:
    pass

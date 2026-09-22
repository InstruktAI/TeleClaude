"""This session's live declared paths, with the time each was declared."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import DECLARATIONS_DIR, safe_path_component

from ._types import DeclarationEvidence

logger = get_logger(__name__)

__all__ = ["clear", "declare", "discard", "live_declarations"]


def declare(session_id: str, paths: Iterable[str]) -> None:
    """Add each path to the session's live declared set at the current instant."""
    now = datetime.now(UTC).isoformat()
    raw = _read_raw(session_id)
    for path in paths:
        raw[path] = now
    _write_raw(session_id, raw)


def live_declarations(session_id: str) -> tuple[DeclarationEvidence, ...]:
    """Return the session's live declared paths, each with its declared instant."""
    raw = _read_raw(session_id)
    return tuple(
        sorted(
            (
                DeclarationEvidence(path=path, declared_at=datetime.fromisoformat(declared_at))
                for path, declared_at in raw.items()
            ),
            key=lambda declaration: (declaration.declared_at, declaration.path),
        )
    )


def clear(session_id: str, paths: Iterable[str]) -> tuple[str, ...]:
    """Remove the named paths, and any live declaration of a directory a named path sits beneath.

    Returns the declared paths actually removed.
    """
    named = tuple(paths)
    if not named:
        return ()
    raw = _read_raw(session_id)
    cleared = tuple(
        declared_path
        for declared_path in raw
        if declared_path in named or any(named_path.startswith(f"{declared_path}/") for named_path in named)
    )
    if not cleared:
        return ()
    for declared_path in cleared:
        del raw[declared_path]
    _write_raw(session_id, raw)
    return cleared


def discard(session_id: str) -> None:
    """Remove the session's declaration record entirely."""
    _record_path(session_id).unlink(missing_ok=True)


def _record_path(session_id: str) -> Path:
    return DECLARATIONS_DIR / f"{safe_path_component(session_id)}.json"


def _read_raw(session_id: str) -> dict[str, str]:
    record_path = _record_path(session_id)
    if not record_path.exists():
        return {}
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("declaration record is not a JSON object")
        return {str(path): str(declared_at) for path, declared_at in payload.items()}
    except (OSError, ValueError) as exc:
        # Degrade to the same nothing-declared-yet state as an absent record:
        # raising here would strand this session's own telec code surface
        # (lint/commit/owners) until the file is manually removed.
        logger.warning("Unreadable declaration record", session_id=session_id, error=str(exc))
        return {}


def _write_raw(session_id: str, paths: dict[str, str]) -> None:
    DECLARATIONS_DIR.mkdir(parents=True, exist_ok=True)
    record_path = _record_path(session_id)
    temp_path = record_path.with_suffix(f"{record_path.suffix}.tmp")
    serialized = json.dumps(paths, ensure_ascii=True, indent=2, sort_keys=True)
    with temp_path.open("w", encoding="utf-8") as file_handle:
        file_handle.write(serialized)
        file_handle.flush()
        os.fsync(file_handle.fileno())
    os.replace(temp_path, record_path)

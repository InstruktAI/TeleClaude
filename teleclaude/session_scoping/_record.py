"""This session's live declared paths, with the time each was declared."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config._file_io import FileTransaction, file_transaction
from teleclaude.paths import (
    LEGACY_DECLARATIONS_DIR,
    SESSION_DECLARATIONS_FILENAME,
    safe_path_component,
    session_tmp_dir,
)

from ._types import DeclarationEvidence

logger = get_logger(__name__)

__all__ = ["clear", "declare", "live_declarations"]


def declare(session_id: str, paths: Iterable[str]) -> None:
    """Add each path to the session's live declared set at the current instant."""
    now = datetime.now(UTC).isoformat()
    record_path = _record_path(session_id)
    with file_transaction(record_path) as transaction:
        raw = _read_raw(transaction, session_id)
        for path in paths:
            raw[path] = now
        _write_raw(transaction, raw)


def live_declarations(session_id: str) -> tuple[DeclarationEvidence, ...]:
    """Return the session's live declared paths, each with its declared instant."""
    record_path = _record_path(session_id)
    with file_transaction(record_path) as transaction:
        raw = _read_raw(transaction, session_id)
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
    record_path = _record_path(session_id)
    with file_transaction(record_path) as transaction:
        raw = _read_raw(transaction, session_id)
        cleared = tuple(
            declared_path
            for declared_path in raw
            if declared_path in named or any(named_path.startswith(f"{declared_path}/") for named_path in named)
        )
        if not cleared:
            return ()
        for declared_path in cleared:
            del raw[declared_path]
        _write_raw(transaction, raw)
    return cleared


def _record_path(session_id: str) -> Path:
    return session_tmp_dir(session_id) / SESSION_DECLARATIONS_FILENAME


def _read_raw(transaction: FileTransaction, session_id: str) -> dict[str, str]:
    try:
        if not transaction.path.exists():
            legacy_path = LEGACY_DECLARATIONS_DIR / f"{safe_path_component(session_id)}.json"
            if not legacy_path.exists():
                return {}
            # One-time forward migration: move the old session record under its session TMPDIR.
            transaction.replace_text(legacy_path.read_text(encoding="utf-8"), creation_mode=0o600)
            legacy_path.unlink()
        serialized = transaction.read_text(encoding="utf-8")
        payload = json.loads(serialized)
        if not isinstance(payload, dict):
            raise ValueError("declaration record is not a JSON object")
        return {str(path): str(declared_at) for path, declared_at in payload.items()}
    except (OSError, ValueError) as exc:
        # Degrade to the same nothing-declared-yet state as an absent record:
        # raising here would strand this session's own telec code surface
        # (lint/commit/owners) until the file is manually removed.
        logger.warning("Unreadable declaration record", session_id=session_id, error=str(exc))
        return {}


def _write_raw(transaction: FileTransaction, paths: dict[str, str]) -> None:
    serialized = json.dumps(paths, ensure_ascii=True, indent=2, sort_keys=True)
    transaction.replace_text(serialized, creation_mode=0o600)

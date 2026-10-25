"""This session's live declared paths, with the time each was declared."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import SESSION_DECLARATIONS_FILENAME, session_tmp_dir

from ._types import DeclarationEvidence

logger = get_logger(__name__)

__all__ = ["clear", "declare", "live_declarations"]

_RECORD_ENCODING: Final = "utf-8"


def declare(session_id: str, paths: Iterable[str]) -> None:
    """Add each path to the session's live declared set at the current instant."""
    now = datetime.now(UTC).isoformat()
    record_path = _record_path(session_id)
    with file_transaction(record_path) as transaction:
        raw = _read_raw(transaction.path, session_id)
        for path in paths:
            raw[path] = now
        _write_raw(transaction, raw)


def live_declarations(session_id: str) -> tuple[DeclarationEvidence, ...]:
    """Return the session's live declared paths, each with its declared instant.

    Reading takes no lock and creates nothing: writers replace the record
    atomically, so a reader sees one complete version, and an absent record or
    session TMPDIR reads as nothing declared.
    """
    raw = _read_raw(_record_path(session_id), session_id)
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
        raw = _read_raw(transaction.path, session_id)
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


def _read_raw(record_path: Path, session_id: str) -> dict[str, str]:
    try:
        payload = json.loads(record_path.read_text(encoding=_RECORD_ENCODING))
        if not isinstance(payload, dict):
            raise ValueError("declaration record is not a JSON object")
        return {str(path): str(declared_at) for path, declared_at in payload.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        # Degrade to the same nothing-declared-yet state as an absent record:
        # raising here would strand this session's own telec repo surface
        # (lint/commit/owners) until the file is manually removed.
        logger.warning("Unreadable declaration record", session_id=session_id, error=str(exc))
        return {}


def _write_raw(transaction: FileTransaction, paths: dict[str, str]) -> None:
    serialized = json.dumps(paths, ensure_ascii=True, indent=2, sort_keys=True)
    transaction.replace_text(serialized, creation_mode=0o600)

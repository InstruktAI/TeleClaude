"""Session identity marker containing only the session id."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path

from teleclaude.constants import MarkerState
from teleclaude.core.operation_caller_identity import get_caller_session_id

_IDENTITY_FILENAME = "teleclaude_identity.json"
_SESSION_ID_FIELD = "session_id"


class SessionIdentityMarkerEnvironmentVariable(StrEnum):
    """Environment variables that locate the current process's session marker."""

    TMPDIR = "TMPDIR"
    TMP = "TMP"
    TEMP = "TEMP"


def _identity_path() -> Path | None:
    """Return the path to the session identity file, or None if no TMPDIR."""
    tmpdir = _session_marker_directory()
    if not tmpdir:
        return None
    return Path(tmpdir) / _IDENTITY_FILENAME


def _session_marker_directory() -> str | None:
    """Return the first directory variable that carries the session marker."""
    for variable in SessionIdentityMarkerEnvironmentVariable:
        value = os.environ.get(variable)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        if value:
            return value
    return None


def inspect_session_identity_marker() -> tuple[MarkerState, str | None]:
    """Return the marker state and its direct session id, without context overrides."""
    path = _identity_path()
    if path is None:
        return MarkerState.ABSENT, None
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return MarkerState.ABSENT, None
    except OSError:
        return MarkerState.INVALID, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return MarkerState.INVALID, None
    if not isinstance(data, dict):
        return MarkerState.INVALID, None
    session_id = data.get(_SESSION_ID_FIELD)
    if not isinstance(session_id, str) or not session_id.strip():
        return MarkerState.INVALID, None
    return MarkerState.VALID, session_id.strip()


def get_session_id() -> str | None:
    """Return the operation-context session id or the file's session pointer."""
    override = get_caller_session_id()
    if override:
        return override
    return inspect_session_identity_marker()[1]


def _atomic_write_identity(path: Path, session_id: str) -> None:
    """Atomically write the session-id pointer."""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({_SESSION_ID_FIELD: session_id}, f, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)


def write_session_identity_to(directory: Path, session_id: str) -> None:
    """Write the session-id pointer into an explicit session TMPDIR."""
    _atomic_write_identity(directory / _IDENTITY_FILENAME, session_id)

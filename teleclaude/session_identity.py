"""Unified session identity resolution via the file-based marker contract.

All session identity is stored in ``$TMPDIR/teleclaude_identity.json``.
The daemon writes session_id at tmux creation time and adds session_token
and system_role during bootstrap.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_IDENTITY_FILENAME = "teleclaude_identity.json"


def _identity_path() -> Path | None:
    """Return the path to the session identity file, or None if no TMPDIR."""
    tmpdir = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP")
    if not tmpdir:
        return None
    return Path(tmpdir) / _IDENTITY_FILENAME


def _read_field(field: str) -> str | None:
    """Read a single field from the identity JSON file."""
    path = _identity_path()
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(field)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def get_session_id() -> str | None:
    """Current TeleClaude session ID from the session identity file.

    All sessions (tmux and headless) get a session-scoped TMPDIR with an
    identity file written at bootstrap by the daemon. This is the single
    source of truth for "which session am I in?"
    """
    return _read_field("session_id")


def get_session_token() -> str | None:
    """Daemon-issued auth token for system-principal sessions."""
    return _read_field("session_token")


def get_system_role() -> str | None:
    """System role (worker, orchestrator, integrator, system) for this session."""
    return _read_field("system_role")


def _atomic_write_identity(path: Path, data: dict[str, str | None]) -> None:
    """Atomic write of identity JSON to the given path."""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)


def write_session_identity(
    session_id: str,
    session_token: str | None = None,
    system_role: str | None = None,
) -> None:
    """Write or update the session identity file in the current process's TMPDIR.

    Performs an atomic read-merge-write so that fields written by earlier
    stages (e.g. session_id written at tmux creation) are preserved when
    later stages add token and role.
    """
    path = _identity_path()
    if path is None:
        raise RuntimeError("Cannot write session identity: no TMPDIR set")
    _write_identity_fields(path, session_id, session_token, system_role)


def write_session_identity_to(
    directory: Path,
    session_id: str,
    session_token: str | None = None,
    system_role: str | None = None,
    human_role: str | None = None,
) -> None:
    """Write or update the session identity file in an explicit directory.

    Used by the daemon to write into a session's TMPDIR without mutating
    the daemon process's own environment.
    """
    path = directory / _IDENTITY_FILENAME
    _write_identity_fields(path, session_id, session_token, system_role, human_role)


def _write_identity_fields(
    path: Path,
    session_id: str,
    session_token: str | None,
    system_role: str | None,
    human_role: str | None = None,
) -> None:
    existing: dict[str, str | None] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            existing = raw
    except (OSError, json.JSONDecodeError):
        pass

    existing["session_id"] = session_id
    if session_token is not None:
        existing["session_token"] = session_token
    if system_role is not None:
        existing["system_role"] = system_role
    if human_role is not None:
        existing["human_role"] = human_role

    _atomic_write_identity(path, existing)

"""Session-scoped, dirty-state-bound disclaimer state for checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, Repo
from teleclaude.hooks.checkpoint_flags import checkpoint_flag_path

logger = get_logger("teleclaude.hooks.checkpoint_disclaimers")

CHECKPOINT_DISCLAIMED_SNAPSHOTS_FLAG = "teleclaude_checkpoint_disclaimed_snapshots_v1"

_MARKER_VERSION = 1
_TEXT_ENCODING = "utf-8"
_TEXT_WRITE_MODE = "w"
_BINARY_READ_MODE = "rb"
_PORCELAIN_FORMAT = "--porcelain=v1"
_UNTRACKED_ALL = "--untracked-files=all"
_NUL = "\x00"
_PATH_SEPARATOR = "--"
_RENAME_OR_COPY = frozenset({"R", "C"})
_HASH_NAME = "sha256"
_JSON_SEPARATORS = (",", ":")
_MODE_MASK = 0o7777
_OCTAL_FORMAT = "o"
_GIT_SUBMODULE_MODE = "160000"
_HEAD_REFERENCE = "HEAD"
_TREE_ZERO_FORMAT = "-z"
_FINGERPRINT_CHUNK_SIZE = 1024 * 1024
_MARKER_VERSION_KEY = "version"
_MARKER_SNAPSHOTS_KEY = "snapshots"
_SNAPSHOT_PATH_KEY = "path"
_SNAPSHOT_FINGERPRINT_KEY = "fingerprint"
_SNAPSHOT_HEAD_KEY = "head"
_SNAPSHOT_KIND_KEY = "kind"
_SNAPSHOT_MODE_KEY = "mode"
_SNAPSHOT_PAYLOAD_KEY = "payload"
_SNAPSHOT_SUBMODULE_HEAD_KEY = "submodule_head"
_SNAPSHOT_ENTRIES_KEY = "entries"
_SNAPSHOT_ENTRY_PATH_KEY = "path"
_SNAPSHOT_ENTRY_STATE_KEY = "state"
_MISSING_PATH_KIND = "missing"
_REGULAR_PATH_KIND = "regular"
_SYMLINK_PATH_KIND = "symlink"
_SUBMODULE_PATH_KIND = "submodule"
_MISSING_PAYLOAD = ""
_INVALID_MARKER_LOG = "Checkpoint disclaimer marker is invalid; retaining no exemptions"
_READ_FAILED_LOG = "Failed to read checkpoint disclaimer marker"
_RECONCILE_FAILED_LOG = "Failed to reconcile checkpoint disclaimer state"
_CLEAR_FAILED_LOG = "Failed to clear checkpoint disclaimer state"
_RECORD_FAILED_LOG = "Failed to record checkpoint disclaimer state"


class DisclaimerPathKind(StrEnum):
    """Filesystem kinds that can define a disclaimed Git path's dirty state."""

    MISSING = _MISSING_PATH_KIND
    REGULAR = _REGULAR_PATH_KIND
    SYMLINK = _SYMLINK_PATH_KIND
    SUBMODULE = _SUBMODULE_PATH_KIND


@dataclass(frozen=True)
class DisclaimerSnapshot:
    """A repository-relative path and its opaque dirty-state identity."""

    path: str
    fingerprint: str


@dataclass(frozen=True)
class DisclaimerMarker:
    """The versioned session marker persisted for checkpoint reconciliation."""

    snapshots: tuple[DisclaimerSnapshot, ...]


class SnapshotEntry(TypedDict):
    """One dirty path nested inside a submodule snapshot."""

    path: str
    state: SnapshotRecord


class SnapshotRecord(TypedDict, total=False):
    """Canonical fields whose encoded form defines one dirty-state identity."""

    head: str
    kind: str
    mode: str
    payload: str
    submodule_head: str
    entries: list[SnapshotEntry]


def record_disclaimed_paths(session_id: str, project_root: Path, paths: list[str]) -> None:
    """Capture all requested dirty states before replacing this marker."""
    if not paths:
        return
    try:
        dirty_paths = _dirty_paths(project_root)
        snapshots = tuple(_capture_snapshot(project_root, path, dirty_paths) for path in paths)
        marker = _read_marker(session_id)
        existing = {} if marker is None else {snapshot.path: snapshot for snapshot in marker.snapshots}
        existing.update({snapshot.path: snapshot for snapshot in snapshots})
        ordered = tuple(sorted(existing.values(), key=lambda item: item.path))
        _write_marker(session_id, DisclaimerMarker(snapshots=ordered))
    except (GitCommandError, InvalidGitRepositoryError, OSError, ValueError) as exc:
        logger.warning(_RECORD_FAILED_LOG, session_id=session_id, error=str(exc))
        raise OSError(str(exc)) from exc
    logger.debug("Checkpoint disclaimed snapshots recorded", session_id=session_id, paths=paths)


def clear_disclaimed_paths(session_id: str, paths: list[str]) -> None:
    """Remove committed paths from this session's versioned disclaimer marker."""
    if not paths:
        return
    try:
        marker = _read_marker(session_id)
        if marker is None:
            return
        committed_paths = set(paths)
        remaining = tuple(snapshot for snapshot in marker.snapshots if snapshot.path not in committed_paths)
        _replace_or_remove_marker(session_id, DisclaimerMarker(snapshots=remaining))
    except OSError as exc:
        logger.warning(_CLEAR_FAILED_LOG, session_id=session_id, error=str(exc))


def reconcile_disclaimed_paths(session_id: str, project_root: Path, dirty_paths: set[str]) -> set[str]:
    """Retain only exact dirty-state matches and fail toward a new checkpoint prompt."""
    try:
        marker = _read_marker(session_id)
        if marker is None:
            return set()
        current_dirty_paths = _dirty_paths(project_root)
        retained: list[DisclaimerSnapshot] = []
        for snapshot in marker.snapshots:
            if snapshot.path not in dirty_paths or snapshot.path not in current_dirty_paths:
                continue
            try:
                current = _capture_snapshot(project_root, snapshot.path, dirty_paths)
            except (GitCommandError, InvalidGitRepositoryError, OSError, ValueError) as exc:
                logger.warning(_RECONCILE_FAILED_LOG, session_id=session_id, path=snapshot.path, error=str(exc))
                continue
            if current.fingerprint == snapshot.fingerprint:
                retained.append(snapshot)
        reconciled = DisclaimerMarker(snapshots=tuple(retained))
        if reconciled != marker:
            _replace_or_remove_marker(session_id, reconciled)
        return {snapshot.path for snapshot in retained}
    except OSError as exc:
        logger.warning(_RECONCILE_FAILED_LOG, session_id=session_id, error=str(exc))
        return set()


def _capture_snapshot(project_root: Path, path: str, dirty_paths: set[str]) -> DisclaimerSnapshot:
    """Capture one currently dirty path without following its terminal symlink."""
    if path not in dirty_paths:
        raise OSError(f"Disclaimed path is not dirty: {path}")
    record = _snapshot_record(project_root, path, visited_roots=set())
    return DisclaimerSnapshot(path=path, fingerprint=_fingerprint(record))


def _snapshot_record(project_root: Path, path: str, *, visited_roots: set[Path]) -> SnapshotRecord:
    """Build a canonical record for one Git path's filesystem and index state."""
    full_path = project_root / path
    head_entry = _head_entry(project_root, path)
    submodule_mode = _git_path_mode(project_root, path) == _GIT_SUBMODULE_MODE
    try:
        metadata = full_path.lstat()
    except FileNotFoundError:
        return {
            _SNAPSHOT_HEAD_KEY: head_entry,
            _SNAPSHOT_KIND_KEY: DisclaimerPathKind.MISSING.value,
            _SNAPSHOT_MODE_KEY: _MISSING_PAYLOAD,
            _SNAPSHOT_PAYLOAD_KEY: _MISSING_PAYLOAD,
        }
    if submodule_mode and stat.S_ISDIR(metadata.st_mode):
        return _submodule_snapshot_record(full_path, head_entry, visited_roots)
    if stat.S_ISREG(metadata.st_mode):
        payload = _regular_file_digest(full_path)
        kind = DisclaimerPathKind.REGULAR
    elif stat.S_ISLNK(metadata.st_mode):
        payload = _symlink_digest(full_path)
        kind = DisclaimerPathKind.SYMLINK
    else:
        raise OSError(f"Unsupported disclaimed path type: {path}")
    return {
        _SNAPSHOT_HEAD_KEY: head_entry,
        _SNAPSHOT_KIND_KEY: kind.value,
        _SNAPSHOT_MODE_KEY: format(metadata.st_mode & _MODE_MASK, _OCTAL_FORMAT),
        _SNAPSHOT_PAYLOAD_KEY: payload,
    }


def _submodule_snapshot_record(path: Path, head_entry: str, visited_roots: set[Path]) -> SnapshotRecord:
    """Capture checked-out HEAD and each nested dirty entry of one submodule."""
    root = path.resolve()
    if root in visited_roots:
        raise OSError(f"Nested submodule cycle detected: {path}")
    nested_visited_roots = visited_roots | {root}
    repository = Repo(str(root))
    nested_dirty_paths = _dirty_paths(root)
    entries: list[SnapshotEntry] = []
    for nested_path in sorted(nested_dirty_paths):
        entries.append(
            SnapshotEntry(
                path=nested_path,
                state=_snapshot_record(root, nested_path, visited_roots=nested_visited_roots),
            )
        )
    return {
        _SNAPSHOT_HEAD_KEY: head_entry,
        _SNAPSHOT_KIND_KEY: DisclaimerPathKind.SUBMODULE.value,
        _SNAPSHOT_SUBMODULE_HEAD_KEY: repository.git.rev_parse(_HEAD_REFERENCE).strip(),
        _SNAPSHOT_ENTRIES_KEY: entries,
    }


def _regular_file_digest(path: Path) -> str:
    """Stream a regular file into an opaque state digest."""
    digest = hashlib.new(_HASH_NAME)
    with path.open(_BINARY_READ_MODE) as handle:
        while chunk := handle.read(_FINGERPRINT_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _symlink_digest(path: Path) -> str:
    """Hash a link target without resolving the link it names."""
    return _digest_bytes(os.readlink(path).encode(_TEXT_ENCODING))


def _digest_bytes(value: bytes) -> str:
    """Return the opaque digest of binary state material."""
    digest = hashlib.new(_HASH_NAME)
    digest.update(value)
    return digest.hexdigest()


def _head_entry(project_root: Path, path: str) -> str:
    """Return the HEAD tree identity for this exact path, or empty when absent."""
    output = Repo(str(project_root)).git.ls_tree(_TREE_ZERO_FORMAT, _HEAD_REFERENCE, _PATH_SEPARATOR, path)
    return output.removesuffix(_NUL)


def _git_path_mode(project_root: Path, path: str) -> str:
    """Return the index mode for one path, preserving Git's submodule identity."""
    output = Repo(str(project_root)).git.ls_files("--stage", _PATH_SEPARATOR, path)
    return output.split(maxsplit=1)[0] if output else _MISSING_PAYLOAD


def _dirty_paths(project_root: Path) -> set[str]:
    """Read every dirty Git path with porcelain-v1 NUL framing preserved."""
    output = Repo(str(project_root)).git.status(_PORCELAIN_FORMAT, _UNTRACKED_ALL, _TREE_ZERO_FORMAT)
    tokens = output.split(_NUL)
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        status = token[:2]
        path = token[3:]
        if status[0] in _RENAME_OR_COPY:
            index += 1
        paths.add(path)
    return paths


def _fingerprint(record: SnapshotRecord) -> str:
    """Hash the canonical structured state record without exposing it to callers."""
    encoded = json.dumps(record, ensure_ascii=True, separators=_JSON_SEPARATORS, sort_keys=True).encode(_TEXT_ENCODING)
    return _digest_bytes(encoded)


def _read_marker(session_id: str) -> DisclaimerMarker | None:
    """Read a valid versioned marker; legacy, malformed, and unreadable state holds none."""
    marker_path = _marker_path(session_id)
    if not marker_path.exists():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding=_TEXT_ENCODING))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(_READ_FAILED_LOG, session_id=session_id, error=str(exc))
        return None
    marker = _parse_marker(payload)
    if marker is None:
        logger.warning(_INVALID_MARKER_LOG, session_id=session_id)
    return marker


def _parse_marker(payload: object) -> DisclaimerMarker | None:
    """Validate the small versioned marker schema before checkpoint consumption."""
    if not isinstance(payload, dict):
        return None
    if payload.get(_MARKER_VERSION_KEY) != _MARKER_VERSION:
        return None
    raw_snapshots = payload.get(_MARKER_SNAPSHOTS_KEY)
    if not isinstance(raw_snapshots, list):
        return None
    snapshots: list[DisclaimerSnapshot] = []
    seen_paths: set[str] = set()
    for raw_snapshot in raw_snapshots:
        if not isinstance(raw_snapshot, dict):
            return None
        path = raw_snapshot.get(_SNAPSHOT_PATH_KEY)
        fingerprint = raw_snapshot.get(_SNAPSHOT_FINGERPRINT_KEY)
        if not isinstance(path, str) or not path or not isinstance(fingerprint, str) or not fingerprint:
            return None
        if path in seen_paths:
            return None
        seen_paths.add(path)
        snapshots.append(DisclaimerSnapshot(path=path, fingerprint=fingerprint))
    return DisclaimerMarker(snapshots=tuple(snapshots))


def _write_marker(session_id: str, marker: DisclaimerMarker) -> None:
    """Persist the complete marker after all requested snapshots succeeded."""
    marker_path = _marker_path(session_id)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        _MARKER_VERSION_KEY: _MARKER_VERSION,
        _MARKER_SNAPSHOTS_KEY: [
            {
                _SNAPSHOT_PATH_KEY: snapshot.path,
                _SNAPSHOT_FINGERPRINT_KEY: snapshot.fingerprint,
            }
            for snapshot in marker.snapshots
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=True, separators=_JSON_SEPARATORS, sort_keys=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode=_TEXT_WRITE_MODE,
            encoding=_TEXT_ENCODING,
            dir=marker_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(marker_path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _replace_or_remove_marker(session_id: str, marker: DisclaimerMarker) -> None:
    """Persist remaining snapshots or remove an empty marker."""
    if marker.snapshots:
        _write_marker(session_id, marker)
    else:
        _marker_path(session_id).unlink(missing_ok=True)


def _marker_path(session_id: str) -> Path:
    """Return the current schema marker, leaving legacy path-only state unread."""
    return checkpoint_flag_path(session_id, CHECKPOINT_DISCLAIMED_SNAPSHOTS_FLAG)

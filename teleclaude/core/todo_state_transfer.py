"""Copy workflow-owned todo databases to another computer's project checkouts."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.config_roster import read_local_computer_name
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.services.project_catalog.service import get_project_catalog_service
from teleclaude.slug import validate_slug
from teleclaude.transport.peer_heartbeat import PeerAddress, PeerNotOnline, lookup_peer_address

logger = get_logger(__name__)

_USER_TOOL_DIRECTORY: Final[Path] = Path(".local") / "bin"
_SYNC_TOOL_NAME: Final[str] = "sqlite3_rsync"
_REMOTE_TELEC_PATH: Final[str] = ".local/bin/telec"
_REMOTE_SYNC_TOOL_PATH: Final[str] = ".local/bin/sqlite3_rsync"
_SSH_COMMAND: Final[str] = "ssh"
_SSH_BATCH_OPTION: Final[str] = "-o"
_SSH_BATCH_VALUE: Final[str] = "BatchMode=yes"
_SSH_ARGUMENT_SEPARATOR: Final[str] = "@"
_SSH_TARGET_SEPARATOR: Final[str] = ":"
_REMOTE_TODO_COMMAND: Final[str] = "todo"
_REMOTE_SYNC_REPLICA_COMMAND: Final[str] = "sync-replica"
_REMOTE_LOCATE_MODE: Final[str] = "locate"
_REMOTE_CHECK_MODE: Final[str] = "check"
_SYNC_EXECUTABLE_OPTION: Final[str] = "--exe"
_JSON_ENCODING: Final[str] = "utf-8"
_READ_ONLY_QUERY: Final[str] = "?mode=ro"
_INTEGRITY_CHECK_SQL: Final[str] = "PRAGMA integrity_check"
_STATUS_FIELD: Final[str] = "status"
_PATH_FIELD: Final[str] = "path"
_REASON_FIELD: Final[str] = "reason"
_DETAIL_FIELD: Final[str] = "detail"
_OK_VALUE: Final[str] = "ok"
_INVALID_PROJECT_SLUG: Final[str] = "project slug must be an unpadded lowercase kebab-case value"
_TRANSFERRED_DETAIL: Final[str] = "copy verified intact"
_SELF_TARGET_DETAIL: Final[str] = "target is this computer"
_LOCAL_NAME_MISSING: Final[str] = "local computer name is unavailable"
_LOCAL_TOOL_MISSING: Final[str] = "sqlite3_rsync is missing; run make install on this computer"
_LOCAL_PROJECT_MISSING: Final[str] = "project is not registered on this computer"
_LOCAL_DATABASE_MISSING: Final[str] = "project todo database is missing on this computer"
_REMOTE_PROJECT_MISSING: Final[str] = "target checkout is absent"
_REMOTE_HELPER_FAILURE: Final[str] = "target could not run the todo sync helper; update TeleClaude on the target"
_REMOTE_INTEGRITY_FAILURE: Final[str] = "target todo database integrity check failed"
_REMOTE_SYNC_FAILURE: Final[str] = "sqlite3_rsync failed; make install must provision it on both computers"
_UNKNOWN_REMOTE_RESULT: Final[str] = "target returned an invalid todo sync response"
_STDERR_TAIL_BYTES: Final[int] = 4000
_TRANSFER_LOG_MESSAGE: Final[str] = "Todo state transferred"
_TRANSFER_SKIPPED_LOG_MESSAGE: Final[str] = "Todo state transfer skipped"
_TRANSFER_FAILED_LOG_MESSAGE: Final[str] = "Todo state transfer failed"


class TransferStatus(StrEnum):
    """One project-to-computer outcome."""

    TRANSFERRED = "transferred"
    SKIPPED = "skipped"
    FAILED = "failed"


class LocateStatus(StrEnum):
    """Whether the target has a readable project checkout."""

    FOUND = "found"
    ABSENT = "absent"


class IntegrityStatus(StrEnum):
    """Result of checking a target todo database."""

    OK = "ok"
    ABSENT = "absent"
    FAILED = "failed"


@dataclass(frozen=True)
class TransferOutcome:
    """Reported result for one project and one target computer."""

    project: str
    computer: str
    status: TransferStatus
    detail: str


@dataclass(frozen=True)
class LocateResult:
    """Target-side project database location answer."""

    status: LocateStatus
    path: str | None
    reason: str | None


@dataclass(frozen=True)
class IntegrityResult:
    """Target-side database integrity answer."""

    status: IntegrityStatus
    detail: str


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class _RemoteCommandError(RuntimeError):
    """A remote process did not complete its declared helper operation."""


async def transfer_todo_state(project_slugs: list[str], computers: list[str]) -> list[TransferOutcome]:
    """Copy and verify each requested project database on every named peer."""
    for project_slug in project_slugs:
        if project_slug != project_slug.strip():
            raise ValueError(_INVALID_PROJECT_SLUG)
        validate_slug(project_slug)

    tool_path = Path.home() / _USER_TOOL_DIRECTORY / _SYNC_TOOL_NAME
    if not tool_path.is_file() or not os.access(tool_path, os.X_OK):
        raise RuntimeError(_LOCAL_TOOL_MISSING)

    local_computer = read_local_computer_name()
    if local_computer is None:
        raise RuntimeError(_LOCAL_NAME_MISSING)

    catalog = get_project_catalog_service()
    local_databases: dict[str, tuple[Path | None, str | None]] = {}
    for project_slug in project_slugs:
        node = catalog.get_by_slug(project_slug)
        if node is None:
            local_databases[project_slug] = (None, _LOCAL_PROJECT_MISSING)
            continue
        try:
            database_path = todos_db_path(node.root)
        except FileNotFoundError:
            local_databases[project_slug] = (None, _LOCAL_DATABASE_MISSING)
            continue
        if database_path.is_file():
            local_databases[project_slug] = (database_path, None)
        else:
            local_databases[project_slug] = (None, _LOCAL_DATABASE_MISSING)

    outcomes: list[TransferOutcome] = []
    for computer in computers:
        transferable_slugs: list[str] = []
        for project_slug in project_slugs:
            source, missing_reason = local_databases[project_slug]
            if source is None:
                outcomes.append(
                    _outcome(
                        project_slug,
                        computer,
                        TransferStatus.FAILED,
                        missing_reason or _LOCAL_DATABASE_MISSING,
                    )
                )
            else:
                transferable_slugs.append(project_slug)
        if not transferable_slugs:
            continue
        if computer == local_computer.value:
            outcomes.extend(
                _outcome(project_slug, computer, TransferStatus.FAILED, _SELF_TARGET_DETAIL)
                for project_slug in transferable_slugs
            )
            continue
        try:
            peer = await lookup_peer_address(computer)
        except (
            OSError,
            TimeoutError,
            RedisError,
            RuntimeError,
            json.JSONDecodeError,
            UnicodeError,
            ValueError,
        ) as error:
            detail = _exception_detail(error)
            outcomes.extend(
                _outcome(project_slug, computer, TransferStatus.FAILED, detail) for project_slug in transferable_slugs
            )
            continue
        if isinstance(peer, PeerNotOnline):
            outcomes.extend(
                _outcome(project_slug, computer, TransferStatus.FAILED, peer.reason)
                for project_slug in transferable_slugs
            )
            continue

        for project_slug in transferable_slugs:
            database_path = local_databases[project_slug][0]
            if database_path is None:
                continue
            try:
                outcome = await _transfer_one(project_slug, database_path, computer, peer, tool_path)
            except (OSError, TimeoutError, ValueError, json.JSONDecodeError, _RemoteCommandError) as error:
                outcome = _outcome(project_slug, computer, TransferStatus.FAILED, _exception_detail(error))
            outcomes.append(outcome)
    for outcome in outcomes:
        _log_outcome(outcome)
    return outcomes


def locate_todo_database(project_slug: str) -> LocateResult:
    """Find this computer's registered checkout database for a project slug."""
    if project_slug != project_slug.strip():
        raise ValueError(_INVALID_PROJECT_SLUG)
    validate_slug(project_slug)
    node = get_project_catalog_service().get_by_slug(project_slug)
    if node is None:
        return LocateResult(LocateStatus.ABSENT, None, _LOCAL_PROJECT_MISSING)
    try:
        database_path = todos_db_path(node.root)
    except FileNotFoundError as error:
        return LocateResult(LocateStatus.ABSENT, None, _exception_detail(error))
    return LocateResult(LocateStatus.FOUND, str(database_path), None)


def check_todo_database(project_slug: str) -> IntegrityResult:
    """Check the registered todo database without acquiring write access."""
    location = locate_todo_database(project_slug)
    if location.status is LocateStatus.ABSENT or location.path is None:
        return IntegrityResult(IntegrityStatus.ABSENT, location.reason or _LOCAL_DATABASE_MISSING)
    database_uri = Path(location.path).as_uri() + _READ_ONLY_QUERY
    try:
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            row = connection.execute(_INTEGRITY_CHECK_SQL).fetchone()
    except (OSError, sqlite3.Error) as error:
        return IntegrityResult(IntegrityStatus.FAILED, _exception_detail(error))
    if row is None:
        return IntegrityResult(IntegrityStatus.FAILED, _UNKNOWN_REMOTE_RESULT)
    result = str(row[0])
    if result == _OK_VALUE:
        return IntegrityResult(IntegrityStatus.OK, result)
    return IntegrityResult(IntegrityStatus.FAILED, result)


async def _transfer_one(
    project_slug: str,
    source: Path,
    computer: str,
    peer: PeerAddress,
    tool_path: Path,
) -> TransferOutcome:
    location = await _remote_locate(project_slug, peer)
    if location.status is LocateStatus.ABSENT:
        return _outcome(project_slug, computer, TransferStatus.SKIPPED, location.reason or _REMOTE_PROJECT_MISSING)
    if location.path is None:
        raise _RemoteCommandError(_UNKNOWN_REMOTE_RESULT)

    destination = f"{peer.user}{_SSH_ARGUMENT_SEPARATOR}{peer.host}{_SSH_TARGET_SEPARATOR}{location.path}"
    sync_result = await _run_process(
        str(tool_path),
        str(source),
        destination,
        _SYNC_EXECUTABLE_OPTION,
        _REMOTE_SYNC_TOOL_PATH,
    )
    if sync_result.returncode != 0:
        stderr = _stderr_detail(sync_result.stderr)
        detail = f"{_REMOTE_SYNC_FAILURE}: {stderr}" if stderr else _REMOTE_SYNC_FAILURE
        raise _RemoteCommandError(detail)

    integrity = await _remote_check(project_slug, peer)
    if integrity.status is not IntegrityStatus.OK:
        return _outcome(
            project_slug,
            computer,
            TransferStatus.FAILED,
            f"{_REMOTE_INTEGRITY_FAILURE}: {integrity.detail}",
        )
    return _outcome(project_slug, computer, TransferStatus.TRANSFERRED, _TRANSFERRED_DETAIL)


async def _remote_locate(project_slug: str, peer: PeerAddress) -> LocateResult:
    answer = await _remote_helper(_REMOTE_LOCATE_MODE, project_slug, peer)
    status = answer.get(_STATUS_FIELD)
    if status == LocateStatus.ABSENT.value:
        reason = answer.get(_REASON_FIELD)
        return LocateResult(LocateStatus.ABSENT, None, reason if isinstance(reason, str) else _REMOTE_PROJECT_MISSING)
    path = answer.get(_PATH_FIELD)
    if status != LocateStatus.FOUND.value or not isinstance(path, str) or not path:
        raise _RemoteCommandError(_UNKNOWN_REMOTE_RESULT)
    return LocateResult(LocateStatus.FOUND, path, None)


async def _remote_check(project_slug: str, peer: PeerAddress) -> IntegrityResult:
    answer = await _remote_helper(_REMOTE_CHECK_MODE, project_slug, peer)
    status = answer.get(_STATUS_FIELD)
    detail = answer.get(_DETAIL_FIELD)
    if not isinstance(detail, str):
        detail = _UNKNOWN_REMOTE_RESULT
    if status == IntegrityStatus.OK.value:
        return IntegrityResult(IntegrityStatus.OK, detail)
    if status == IntegrityStatus.ABSENT.value:
        return IntegrityResult(IntegrityStatus.ABSENT, detail)
    return IntegrityResult(IntegrityStatus.FAILED, detail)


async def _remote_helper(mode: str, project_slug: str, peer: PeerAddress) -> Mapping[str, object]:
    result = await _run_process(
        _SSH_COMMAND,
        _SSH_BATCH_OPTION,
        _SSH_BATCH_VALUE,
        f"{peer.user}{_SSH_ARGUMENT_SEPARATOR}{peer.host}",
        _REMOTE_TELEC_PATH,
        _REMOTE_TODO_COMMAND,
        _REMOTE_SYNC_REPLICA_COMMAND,
        mode,
        project_slug,
    )
    if result.returncode != 0:
        stderr = _stderr_detail(result.stderr)
        detail = f"{_REMOTE_HELPER_FAILURE}: {stderr}" if stderr else _REMOTE_HELPER_FAILURE
        raise _RemoteCommandError(detail)
    decoded: object = json.loads(result.stdout)
    if not isinstance(decoded, dict):
        raise _RemoteCommandError(_UNKNOWN_REMOTE_RESULT)
    return cast(Mapping[str, object], decoded)


async def _run_process(*arguments: str) -> _ProcessResult:
    # SSH and sqlite3_rsync are external executables with no in-process API; argv execution avoids a local shell.
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    returncode = process.returncode
    if returncode is None:
        raise RuntimeError(_UNKNOWN_REMOTE_RESULT)
    return _ProcessResult(returncode, stdout, stderr)


def _outcome(project: str, computer: str, status: TransferStatus, detail: str) -> TransferOutcome:
    return TransferOutcome(project, computer, status, detail)


def _exception_detail(error: Exception) -> str:
    return str(error) or type(error).__name__


def _stderr_detail(stderr: bytes) -> str:
    detail = stderr[-_STDERR_TAIL_BYTES:].decode(_JSON_ENCODING, errors="replace").strip()
    return detail


def _log_outcome(outcome: TransferOutcome) -> None:
    fields: dict[str, str] = {
        "project": outcome.project,
        "computer": outcome.computer,
        _STATUS_FIELD: outcome.status.value,
        _DETAIL_FIELD: outcome.detail,
    }
    if outcome.status is TransferStatus.TRANSFERRED:
        logger.info(_TRANSFER_LOG_MESSAGE, **fields)
    elif outcome.status is TransferStatus.SKIPPED:
        logger.warning(_TRANSFER_SKIPPED_LOG_MESSAGE, **fields)
    else:
        logger.error(_TRANSFER_FAILED_LOG_MESSAGE, **fields)

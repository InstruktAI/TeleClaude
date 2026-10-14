"""Copy workflow-owned todo databases to another computer's project checkouts."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.config.machine import config
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.core.workflow_store.selection import (
    check_workflow_store_integrity,
    get_workflow_transfer_source,
    workflow_store_database_location,
)
from teleclaude.core.workflow_store.types import StoreIntegrityStatus as IntegrityStatus
from teleclaude.core.workflow_store.types import TransferSource
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
_JSON_ENCODING: Final[str] = "utf-8"
_STATUS_FIELD: Final[str] = "status"
_PATH_FIELD: Final[str] = "path"
_REASON_FIELD: Final[str] = "reason"
_DETAIL_FIELD: Final[str] = "detail"
_INVALID_PROJECT_SLUG: Final[str] = "project slug must be an unpadded lowercase kebab-case value"
_TRANSFERRED_DETAIL: Final[str] = "copy verified intact"
_SELF_TARGET_DETAIL: Final[str] = "target is this computer"
_LOCAL_TOOL_MISSING: Final[str] = "sqlite3_rsync is missing; run make install on this computer"
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

    local_computer = config.computer.name

    catalog = get_project_catalog_service()
    local_databases: dict[str, tuple[TransferSource | None, str | None]] = {}
    for project_slug in project_slugs:
        node = catalog.get_by_slug(project_slug)
        if node is None:
            local_databases[project_slug] = (None, str(unregistered_referent(ReferentKind.PROJECT, project_slug)))
            continue
        try:
            source = get_workflow_transfer_source(node.root)
        except FileNotFoundError as error:
            local_databases[project_slug] = (None, _exception_detail(error))
        else:
            local_databases[project_slug] = (source, None if source is not None else _LOCAL_DATABASE_MISSING)

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
        if computer == local_computer:
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
            source = local_databases[project_slug][0]
            if source is None:
                continue
            try:
                outcome = await _transfer_one(project_slug, source, computer, peer, tool_path)
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
        return LocateResult(LocateStatus.ABSENT, None, str(unregistered_referent(ReferentKind.PROJECT, project_slug)))
    try:
        database_path = workflow_store_database_location(node.root)
    except FileNotFoundError as error:
        return LocateResult(LocateStatus.ABSENT, None, _exception_detail(error))
    if database_path is None:
        return LocateResult(LocateStatus.ABSENT, None, _LOCAL_DATABASE_MISSING)
    return LocateResult(LocateStatus.FOUND, database_path, None)


def check_todo_database(project_slug: str) -> IntegrityResult:
    """Check the registered todo database without acquiring write access."""
    if project_slug != project_slug.strip():
        raise ValueError(_INVALID_PROJECT_SLUG)
    validate_slug(project_slug)
    node = get_project_catalog_service().get_by_slug(project_slug)
    if node is None:
        return IntegrityResult(IntegrityStatus.ABSENT, str(unregistered_referent(ReferentKind.PROJECT, project_slug)))
    try:
        status, detail = check_workflow_store_integrity(node.root)
    except FileNotFoundError as error:
        return IntegrityResult(IntegrityStatus.ABSENT, _exception_detail(error))
    return IntegrityResult(IntegrityStatus(status), detail)


async def _transfer_one(
    project_slug: str,
    source: TransferSource,
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
    sync_result = await source.sync_to(tool_path, destination, _REMOTE_SYNC_TOOL_PATH)
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

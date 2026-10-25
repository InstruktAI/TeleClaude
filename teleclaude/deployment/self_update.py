"""The installation's own channel reaction: install the revision its channel admits when its source publishes one.

A relayed ``github.push`` or ``github.release`` of the repository the installation follows is handed to
the running daemon (``reconciliation.installation_reaction``), which launches this module as its own
process — the install stops the daemon that decided it, so the act cannot run inside it. From the event
and this computer's channel the reaction decides whether the event calls for a target; the install act
(``reconciliation.install_act``) then does what every route to live does: it refuses an older target,
prepares the release while the daemon serves, migrates in a stopped window and verifies the start.

A convergence is recorded as pending before anything is fetched and cleared only once the act ended
without failing, so a replay completes whatever an interrupted attempt left undone and a target version is
applied at most once. A release target resolves once and its commit is retained; the alpha channel's
moving mainline is resolved anew on each attempt.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import uuid4

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.core.reconciliation.channel_target import release_tag_of
from teleclaude.core.reconciliation.install_act import InstallRequest, InstallResult, InstallStatus, install
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.deployment import parse_version
from teleclaude.deployment.migration_runner import DeploymentMigrationError, committed_version
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.git import GitCommandError, Repo
from teleclaude.logging_config import setup_logging
from teleclaude.paths import MIGRATION_STATE_PATH

logger = get_logger(__name__)

PENDING_CONVERGENCE_PATH = MIGRATION_STATE_PATH.parent / "self_update_pending.json"

_PUSH_EVENT_TYPE = "github.push"
_RELEASE_EVENT_TYPE = "github.release"
_MAIN_REF = "refs/heads/main"
_PUBLISHED_ACTION = "published"
_REF_FIELD = "ref"
_ACTION_FIELD = "action"
_RELEASE_FIELD = "release"
_TAG_FIELD = "tag_name"
_ALPHA_TARGET = "origin/main"
_TAG_TEMPLATE = "v{major}.{minor}.{patch}"
_TEXT_ENCODING = "utf-8"
_TEMPORARY_NAME = "{name}.{unique}.tmp"
_LOCK_MODE = "a+"
_CONVERGENCE_LOCK_PATH = PENDING_CONVERGENCE_PATH.with_name("self_update_pending.converge.lock")
_INCOMPLETE = "the convergence did not complete and stays pending"
_FAILURE_SEPARATOR = "; "
_PENDING_DIRECTORY = PENDING_CONVERGENCE_PATH.with_name("self_update_pending")
_ENTRY_NAME = "{admitted_ns:020d}-{unique}.json"
_ENTRY_PATTERN = "*.json"
_ENTRY_UNREADABLE_ERROR = "the pending convergence record {path} could not be read: {error}"
_UNINSTALLED_VERSION = "0.0.0"
_TARGET_OPTION = "--target"
_ADMITTED_OPTION = "--admitted"
_FAILED_EXIT_CODE = 1
_FAILED_EVENT = "self_update_failed"
_ENDED_EVENT = "self_update_ended"
_NO_SERIES_ERROR = "stable self-update requires a compatibility series, and this installation declares none"
_UNKNOWN_TARGET_ERROR = "target {target!r} is not an advance this action performs"
_PENDING_SCHEMA_VERSION: Literal[1] = 1
_SCHEMA_VERSION_FIELD = "schema_version"
_PENDING_NOT_A_RECORD_ERROR = "the pending convergence record is not a JSON object"
_PENDING_MIGRATED_EVENT = "self_update_pending_migrated"


class SkipReason(StrEnum):
    """Why an event calls for no convergence on this computer."""

    NOT_MAIN_PUSH = "not_a_push_to_main"
    NOT_PUBLISHED_RELEASE = "not_a_published_release"
    TAG_NOT_VERSION = "release_tag_is_not_a_semantic_version"
    OUTSIDE_SERIES = "release_outside_compatibility_series"


class SelfUpdateError(Exception):
    """A convergence step failed; the message is the reason the action reports."""


_STEP_FAILURES = (SelfUpdateError, ReleasePreparationError, GitCommandError, OSError, ValueError)


class PendingConvergence(BaseModel):
    """A convergence that began and has not finished: where it left from and the target it advances to.

    ``target_commit`` is the immutable commit a release target resolved to, retained before any source
    moves; it is ``None`` while the target is unresolved and for the alpha channel's moving mainline.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _PENDING_SCHEMA_VERSION
    from_version: str
    from_commit: str
    target: str
    target_commit: str | None


class _PendingConvergenceV0(BaseModel):
    """The unversioned record shape stored before release commits were retained; read only by its migration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_version: str
    from_commit: str
    target: str


@dataclass(frozen=True)
class ConvergenceTarget:
    """The ref a channel admits an event to converge to."""

    ref: str


def target_for_event(
    event: ReceivedEvent, channel: ReleaseChannel, series: CompatibilitySeries | None
) -> ConvergenceTarget | SkipReason:
    """Decide from the event and the computer's channel and series whether, and to what, the installation converges."""
    if channel is ReleaseChannel.ALPHA:
        if event.type == _PUSH_EVENT_TYPE and event.data.get(_REF_FIELD) == _MAIN_REF:
            return ConvergenceTarget(ref=_ALPHA_TARGET)
        return SkipReason.NOT_MAIN_PUSH
    if event.type != _RELEASE_EVENT_TYPE or event.data.get(_ACTION_FIELD) != _PUBLISHED_ACTION:
        return SkipReason.NOT_PUBLISHED_RELEASE
    tag = _release_tag(event)
    try:
        version = parse_version(tag)
    except ValueError:
        return SkipReason.TAG_NOT_VERSION
    if channel is ReleaseChannel.STABLE:
        if series is None:
            raise SelfUpdateError(_NO_SERIES_ERROR)
        if not series.admits(version):
            return SkipReason.OUTSIDE_SERIES
    return ConvergenceTarget(ref=_tag_ref(version))


def _release_tag(event: ReceivedEvent) -> str:
    """The published release's tag name; empty when the event carries none."""
    release = event.data.get(_RELEASE_FIELD)
    if not isinstance(release, dict):
        return ""
    tag = release.get(_TAG_FIELD)
    return tag if isinstance(tag, str) else ""


def _tag_ref(version: tuple[int, int, int]) -> str:
    """Rebuild the release tag from its parsed numbers, so no raw event text reaches git."""
    major, minor, patch = version
    return _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)


def _ingest_stored_pending() -> None:
    """Bring a convergence stored as the single earlier record, in either earlier shape, into the per-admission store.

    A record of a newer version, or of neither earlier shape, is refused with its evidence left in place.
    """
    if not PENDING_CONVERGENCE_PATH.exists():
        return
    stored: object = json.loads(PENDING_CONVERGENCE_PATH.read_text(encoding=_TEXT_ENCODING))
    if not isinstance(stored, dict):
        raise SelfUpdateError(_PENDING_NOT_A_RECORD_ERROR)
    if _SCHEMA_VERSION_FIELD in stored:
        pending = PendingConvergence.model_validate(stored)
    else:
        legacy = _PendingConvergenceV0.model_validate(stored)
        pending = PendingConvergence(
            from_version=legacy.from_version,
            from_commit=legacy.from_commit,
            target=legacy.target,
            target_commit=None,
        )
        logger.info(_PENDING_MIGRATED_EVENT, from_commit=legacy.from_commit, target=legacy.target)
    _write_entry(pending, admitted_ns=PENDING_CONVERGENCE_PATH.stat().st_mtime_ns)
    PENDING_CONVERGENCE_PATH.unlink()


def _write_entry(pending: PendingConvergence, *, admitted_ns: int, path: Path | None = None) -> Path:
    """Store one admission's convergence as a record of its own, atomically; a given ``path`` rewrites that record."""
    _PENDING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    entry = path or _PENDING_DIRECTORY / _ENTRY_NAME.format(admitted_ns=admitted_ns, unique=uuid4().hex)
    temporary = entry.with_name(_TEMPORARY_NAME.format(name=entry.name, unique=uuid4().hex))
    temporary.write_text(pending.model_dump_json(), encoding=_TEXT_ENCODING)
    temporary.replace(entry)
    return entry


def _read_entry(path: Path) -> PendingConvergence:
    try:
        return PendingConvergence.model_validate_json(path.read_text(encoding=_TEXT_ENCODING))
    except (OSError, ValueError) as error:
        raise SelfUpdateError(_ENTRY_UNREADABLE_ERROR.format(path=path, error=error)) from error


def _entries() -> list[Path]:
    """The stored convergences in the order they were admitted."""
    if not _PENDING_DIRECTORY.is_dir():
        return []
    return sorted(_PENDING_DIRECTORY.glob(_ENTRY_PATTERN))


@contextmanager
def _convergence_lock() -> Iterator[None]:
    """Hold the one lock the stored convergences are processed under.

    Overlapping reactions each run as a process of their own; serializing them keeps one from retrying
    or discarding a convergence while another is part-way through it.
    """
    PENDING_CONVERGENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _CONVERGENCE_LOCK_PATH.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_admitted_target(target: str, layout: InstallationLayout | None = None) -> None:
    """Keep one admission durably, as a convergence of its own, before its process launches and the event is acknowledged.

    Every admission is its own record with the source it left from, so it never depends on what an earlier
    one left unfinished, on who holds the lock, or on another admission of the same moving ref: each
    record is retried with its own retained identity and discarded only when its own convergence settled.
    """
    resolved = layout or InstallationLayout()
    pending = PendingConvergence(
        from_version=_active_version(resolved),
        from_commit=resolved.active_revision() or _UNINSTALLED_VERSION,
        target=_validated_target(target),
        target_commit=None,
    )
    _write_entry(pending, admitted_ns=time.time_ns())


def _validated_target(target: str) -> str:
    """The recorded target, accepted only as the mainline ref or a release tag rebuilt from its numbers."""
    if target == _ALPHA_TARGET:
        return target
    try:
        return _tag_ref(parse_version(target))
    except ValueError as error:
        raise SelfUpdateError(_UNKNOWN_TARGET_ERROR.format(target=target)) from error


def _active_version(layout: InstallationLayout) -> str:
    """The project version the active release declares, which its migrations are keyed to; none when nothing is installed."""
    active = layout.active_revision()
    if active is None:
        return _UNINSTALLED_VERSION
    try:
        return committed_version(Repo(str(layout.repository)), active)
    except (DeploymentMigrationError, GitCommandError, OSError):
        return _UNINSTALLED_VERSION


def _install_entry(path: Path, ports: LiveInstallPorts, layout: InstallationLayout) -> None:
    """Install one stored convergence and discard its record once the act settled; the commit it resolved is retained first."""
    pending = _read_entry(path)
    release_tag = release_tag_of(pending.target)
    retained = pending
    if release_tag is not None and pending.target_commit is None:
        ports.fetch(None)
        retained = pending.model_copy(update={"target_commit": ports.resolve(pending.target)})
        _write_entry(retained, admitted_ns=0, path=path)
    result = install(
        InstallRequest(target=retained.target_commit or retained.target, release_tag=release_tag), ports, layout
    )
    log = logger.error if result.status is InstallStatus.FAILED else logger.info
    log(_ENDED_EVENT, target=pending.target, status=result.status, reason=result.reason)
    if not _settled(result):
        raise SelfUpdateError(result.reason or _INCOMPLETE)
    path.unlink(missing_ok=True)


def _settled(result: InstallResult) -> bool:
    """Whether the act left nothing for a replay: it installed, changed nothing, or found the target already contained.

    Any other refusal — a transition the rule refuses, an install already in progress — and every failure
    leaves the convergence pending and is reported as incomplete.
    """
    if result.status in (InstallStatus.COMPLETED, InstallStatus.UNCHANGED):
        return True
    return result.status is InstallStatus.REFUSED and result.contained


def converge(layout: InstallationLayout | None = None) -> None:
    """Settle every stored convergence in the order admitted, serialized with every other reaction."""
    with _convergence_lock():
        _converge_locked(layout or InstallationLayout())


def _converge_locked(resolved: InstallationLayout) -> None:
    """Install each stored convergence from its own retained identity.

    One that does not settle stays stored, untouched, and does not stop the others: a later release may be
    the very one that repairs what an earlier one could not do. The process ends as incomplete when any
    did not settle.
    """
    ports = LiveInstallPorts(resolved)
    _ingest_stored_pending()
    failures: list[str] = []
    for path in _entries():
        _attempt(partial(_install_entry, path, ports, resolved), failures)
    if failures:
        raise SelfUpdateError(_FAILURE_SEPARATOR.join(failures))


def _attempt(step: Callable[[], object], failures: list[str]) -> None:
    try:
        step()
    except _STEP_FAILURES as error:
        logger.error(_FAILED_EVENT, error=str(error), exc_info=True)
        failures.append(str(error))


def main(arguments: list[str] | None = None) -> int:
    """Converge this installation to the target named by ``--target``; non-zero when the act failed."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_TARGET_OPTION, required=True)
    parser.add_argument(_ADMITTED_OPTION, action="store_true")
    options = parser.parse_args(arguments)
    try:
        if not options.admitted:
            record_admitted_target(options.target)
        converge()
    except _STEP_FAILURES as error:
        logger.error(_FAILED_EVENT, error=str(error), exc_info=True)
        print(str(error), file=sys.stderr)
        return _FAILED_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

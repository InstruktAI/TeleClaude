"""The installation's own channel reaction: install the revision its channel admits when its source signals one.

A signal about the repository the installation follows — a main revision announced green, or a published
release — is handed to the running daemon (``reconciliation.installation_reaction``), which launches this module
as its own process — the install stops the daemon that decided it, so the act cannot run inside it. From the
signal and this computer's channel the reaction decides whether the signal calls for a target; the install act
(``reconciliation.install_act``) then does what every route to live does: it refuses an older target,
prepares the release while the daemon serves, migrates in a stopped window and verifies the start.

Edge admits a green main revision as the full commit it names, so only a revision that passed is ever activated;
stable admits a release inside the compatibility series the active release derives and holds the newest later
release beyond it for the installation inspector
(``local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update``).

A convergence is recorded as pending before anything is fetched and cleared only once the act ended
without failing, so a replay completes whatever an interrupted attempt left undone and a target version is
applied at most once. A release target resolves once and its commit is retained; an edge target is its green
commit from the start. An edge entry that a newer pending green revision overtakes is discarded unactivated.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Final, Literal
from uuid import uuid4

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.core.reconciliation.channel_target import release_tag_of
from teleclaude.core.reconciliation.convergence_decision import DecisionOutcome, HeldRelease
from teleclaude.core.reconciliation.install_act import InstallRequest, InstallResult, InstallStatus, install
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.core.reconciliation.release_transition import transition_refusal
from teleclaude.deployment import parse_version
from teleclaude.deployment.migration_runner import DeploymentMigrationError, committed_version
from teleclaude.git import BadName, GitCommandError, Repo
from teleclaude.logging_config import setup_logging
from teleclaude.paths import MIGRATION_STATE_PATH

logger = get_logger(__name__)

PENDING_CONVERGENCE_PATH = MIGRATION_STATE_PATH.parent / "self_update_pending.json"

_FULL_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
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
_ADMITTED_REASON = "revision {revision} is announced green, so it is the newest the edge channel admits"
_NO_EDGE_SIGNAL_REASON = "the edge channel follows green main revisions, and the signal is not one"
_NOT_A_COMMIT_REASON = "the green revision {revision!r} is not a full commit, so it is never activated"
_RELEASE_ADMITTED_REASON = "release {tag} is inside the compatibility series {series} of the active release {active}"
_RELEASE_HELD_REASON = (
    "release {tag} is beyond the compatibility series {series} of the active release {active}, "
    "so it is held for the installation inspector"
)
_RELEASE_ADMITTED_AND_HELD_REASON = (
    "release {tag} is inside the compatibility series {series} of the active release {active}, "
    "and the later release {held} beyond it is held for the installation inspector"
)
_NO_STABLE_SIGNAL_REASON = "the stable channel follows published releases, and the signal is not one"
_NO_VERSIONED_RELEASE_REASON = "the published release's tag is not a semantic version"
_NOTHING_NEWER_REASON = "no published release is later than the active release {active}"
_VERSION_TEXT = "{major}.{minor}.{patch}"
_SUPERSEDED_EVENT = "self_update_edge_superseded"
_RETIRED_TARGET_EVENT = "self_update_retired_target_discarded"
_UNKNOWN_TARGET_ERROR = "target {target!r} is not an advance this action performs"
_PENDING_SCHEMA_VERSION: Literal[1] = 1
_SCHEMA_VERSION_FIELD = "schema_version"
_PENDING_NOT_A_RECORD_ERROR = "the pending convergence record is not a JSON object"
_PENDING_MIGRATED_EVENT = "self_update_pending_migrated"


class SkipReason(StrEnum):
    """Why an event is no channel signal at all."""

    NOT_A_SIGNAL = "not_a_channel_signal"
    NOT_PUBLISHED_RELEASE = "not_a_published_release"


class SignalKind(StrEnum):
    """The two signals a followed source gives: a main revision announced green, and a published release."""

    GREEN_REVISION = "green_revision"
    RELEASE_PUBLISHED = "release_published"


@dataclass(frozen=True)
class ChannelSignal:
    """One signal about a followed source, in the one shape the decision reads.

    ``repository`` is the canonical ``owner/name``; ``reference`` is the full commit of a green revision or the
    tag of a published release, whichever way the signal arrived.
    """

    repository: str
    kind: SignalKind
    reference: str


class SelfUpdateError(Exception):
    """A convergence step failed; the message is the reason the action reports."""


_STEP_FAILURES = (SelfUpdateError, ReleasePreparationError, GitCommandError, OSError, ValueError)


class PendingConvergence(BaseModel):
    """A convergence that began and has not finished: where it left from and the target it advances to.

    ``target_commit`` is the immutable commit the target resolved to, retained before any source moves: an
    edge target is its green commit from the start, a release target's commit is retained when it resolves and
    is ``None`` until then.
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
    """The ref a channel admits a signal to converge to: a full commit on edge, a release tag on stable."""

    ref: str


@dataclass(frozen=True)
class ChannelDecision:
    """What the channel decided for its signals: the outcome, the sentence that says why, the target it admits
    and the release it holds, either of which may be absent."""

    outcome: DecisionOutcome
    reason: str
    target: ConvergenceTarget | None = None
    held: HeldRelease | None = None


def decide_signals(
    signals: Sequence[ChannelSignal], channel: ReleaseChannel, active: tuple[int, int, int]
) -> ChannelDecision:
    """Decide from the signals of the followed source, this computer's channel and the active release's version
    whether, and to what, the installation converges.

    Edge admits the latest green revision it is given, as the full commit, and nothing else: a pushed revision is
    no signal. Stable derives the compatibility series from the active release, admits the newest later release
    inside it, and holds the newest later release beyond it, so a compatible release is never shadowed by a newer
    breaking one. A release that is not later than the active one calls for nothing.
    """
    if channel is ReleaseChannel.EDGE:
        return _decide_edge(signals)
    return _decide_stable(signals, active)


def _decide_edge(signals: Sequence[ChannelSignal]) -> ChannelDecision:
    green = [signal.reference for signal in signals if signal.kind is SignalKind.GREEN_REVISION]
    if not green:
        return ChannelDecision(DecisionOutcome.SKIPPED, _NO_EDGE_SIGNAL_REASON)
    revision = green[-1]
    if _FULL_COMMIT.fullmatch(revision) is None:
        return ChannelDecision(DecisionOutcome.SKIPPED, _NOT_A_COMMIT_REASON.format(revision=revision))
    return ChannelDecision(
        DecisionOutcome.ADMITTED, _ADMITTED_REASON.format(revision=revision), target=ConvergenceTarget(ref=revision)
    )


def _decide_stable(signals: Sequence[ChannelSignal], active: tuple[int, int, int]) -> ChannelDecision:
    published = [signal for signal in signals if signal.kind is SignalKind.RELEASE_PUBLISHED]
    if not published:
        return ChannelDecision(DecisionOutcome.SKIPPED, _NO_STABLE_SIGNAL_REASON)
    versions = {version: signal for signal in published if (version := _release_version(signal.reference)) is not None}
    if not versions:
        return ChannelDecision(DecisionOutcome.SKIPPED, _NO_VERSIONED_RELEASE_REASON)
    series = CompatibilitySeries.of_version(active)
    later = sorted(version for version in versions if version > active)
    inside = [version for version in later if series.admits(version)]
    beyond = [version for version in later if not series.admits(version)]
    active_text = _version_text(active)
    if not inside and not beyond:
        return ChannelDecision(DecisionOutcome.NOTHING_NEWER, _NOTHING_NEWER_REASON.format(active=active_text))
    target = ConvergenceTarget(ref=_tag_ref(inside[-1])) if inside else None
    held = _held_release(versions[beyond[-1]]) if beyond else None
    if target is not None and held is not None:
        reason = _RELEASE_ADMITTED_AND_HELD_REASON.format(
            tag=target.ref, series=series, active=active_text, held=held.tag
        )
        return ChannelDecision(DecisionOutcome.ADMITTED, reason, target=target, held=held)
    if target is not None:
        reason = _RELEASE_ADMITTED_REASON.format(tag=target.ref, series=series, active=active_text)
        return ChannelDecision(DecisionOutcome.ADMITTED, reason, target=target)
    assert held is not None
    reason = _RELEASE_HELD_REASON.format(tag=held.tag, series=series, active=active_text)
    return ChannelDecision(DecisionOutcome.HELD, reason, held=held)


def _release_version(tag: str) -> tuple[int, int, int] | None:
    """The version a release tag names, or ``None`` when the tag is not a semantic version."""
    try:
        return parse_version(tag)
    except ValueError:
        return None


def _held_release(signal: ChannelSignal) -> HeldRelease:
    """The release a signal names, as the record holds it; the tag is rebuilt from its parsed numbers."""
    version = parse_version(signal.reference)
    return HeldRelease(
        source=signal.repository,
        tag=_tag_ref(version),
        version=_version_text(version),
        held_at=datetime.now(UTC),
    )


def _version_text(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return _VERSION_TEXT.format(major=major, minor=minor, patch=patch)


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
    validated = _validated_target(target)
    pending = PendingConvergence(
        from_version=_active_version(resolved),
        from_commit=resolved.active_revision() or _UNINSTALLED_VERSION,
        target=validated,
        target_commit=validated if _is_commit(validated) else None,
    )
    _write_entry(pending, admitted_ns=time.time_ns())


def _is_commit(target: str) -> bool:
    """Whether the target is a full commit, which is how an edge admission names its green revision."""
    return _FULL_COMMIT.fullmatch(target) is not None


def _validated_target(target: str) -> str:
    """The recorded target, accepted only as a full commit or a release tag rebuilt from its numbers."""
    if _is_commit(target):
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
    """Install one stored convergence and discard its record once the act settled; the commit it resolved is retained first.

    A target that is neither a full commit nor a release tag is a retired moving ref and is discarded. An edge
    entry that a newer pending green revision overtakes is discarded unactivated, here and again when the act is
    about to stop the daemon.
    """
    pending = _read_entry(path)
    release_tag = release_tag_of(pending.target)
    edge_commit = pending.target if _is_commit(pending.target) else None
    if release_tag is None and edge_commit is None:
        logger.warning(_RETIRED_TARGET_EVENT, target=pending.target)
        path.unlink(missing_ok=True)
        return
    retained = pending
    if release_tag is not None and pending.target_commit is None:
        ports.fetch(None)
        retained = pending.model_copy(update={"target_commit": ports.resolve(pending.target)})
        _write_entry(retained, admitted_ns=0, path=path)
    if edge_commit is not None:
        ports.fetch(None)
        if is_superseded(layout, edge_commit, exclude=path):
            logger.info(_SUPERSEDED_EVENT, target=edge_commit)
            path.unlink(missing_ok=True)
            return
    result = install(
        InstallRequest(
            target=retained.target_commit or retained.target,
            release_tag=release_tag,
            is_superseded=partial(is_superseded, layout, exclude=path) if edge_commit is not None else None,
        ),
        ports,
        layout,
    )
    log = logger.error if result.status is InstallStatus.FAILED else logger.info
    log(_ENDED_EVENT, target=pending.target, status=result.status, reason=result.reason)
    if not _settled(result):
        raise SelfUpdateError(result.reason or _INCOMPLETE)
    path.unlink(missing_ok=True)


def is_superseded(layout: InstallationLayout, commit: str, exclude: Path | None = None) -> bool:
    """Whether a pending edge admission names a different commit that is a forward step over ``commit``.

    The one supersession predicate: the converge loop, the act's confirmation at its stop and every other
    caller that resolves an edge target ask it of the pending store. Equal commits are no forward step
    (``transition_refusal`` leaves equality to its caller), so duplicate admissions of one green revision never
    supersede each other. A pending commit the kept repository does not hold yet cannot be placed in history, and
    an unplaceable commit is never taken as proof that ``commit`` is still the newest: the repository is fetched
    once, and a fetch that fails raises so the caller leaves the active release serving. A commit still absent
    after a fetch is not part of the source's history and overtakes nothing.
    """
    others = [other for other in _pending_edge_commits(exclude) if other != commit]
    repository = Repo(str(layout.repository))
    if any(not _holds_commit(repository, other) for other in others):
        LiveInstallPorts(layout).fetch(None)
    return any(_is_forward_step(repository, commit, other) for other in others)


def _holds_commit(repository: Repo, commit: str) -> bool:
    try:
        repository.commit(commit)
    except (GitCommandError, BadName, ValueError):
        return False
    return True


def _is_forward_step(repository: Repo, commit: str, other: str) -> bool:
    try:
        return transition_refusal(repository, commit, other, None) is None
    except (GitCommandError, BadName, ValueError):
        return False


def _pending_edge_commits(exclude: Path | None) -> Iterable[str]:
    """The green commits the pending store still holds for activation, other than the entry ``exclude`` names."""
    for entry in _entries():
        if entry == exclude:
            continue
        try:
            target = _read_entry(entry).target
        except SelfUpdateError:
            continue
        if _is_commit(target):
            yield target


def _settled(result: InstallResult) -> bool:
    """Whether the act left nothing for a replay: it installed, changed nothing, found the target already contained
    or overtaken.

    Any other refusal — a transition the rule refuses, an install already in progress — and every failure
    leaves the convergence pending and is reported as incomplete.
    """
    if result.status in (InstallStatus.COMPLETED, InstallStatus.UNCHANGED):
        return True
    return result.status is InstallStatus.REFUSED and (result.contained or result.superseded)


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

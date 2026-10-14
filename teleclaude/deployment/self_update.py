"""Channel-gated self-update: the maintenance action that converges this installation to its channel's target.

The action is handed the platform event it reacts to as a file. From the event and this computer's
deployment channel it decides whether the event calls for a target the checkout lacks. The alpha
channel reaches its target by advancing the checkout's main branch by fast-forward. A beta or stable
installation selects the release's exact commit in detached HEAD, resolved once and retained, so the
source it runs never depends on what a branch or a moved tag names later. A release advances the source
only to a strictly later version whose history contains the installed commit; an older announcement the
installation already contains leaves it unchanged, and any other transition is refused before the source
moves. The advance is recorded as an ordinary canonical-main activation; its maintenance includes the
installation migrations and controlled daemon window. A recording the maintenance executor refuses leaves
the convergence pending.

A convergence is recorded as pending before anything is fetched and cleared only after its last step
succeeded. Every run completes a pending convergence first, so a replay finishes whatever a failed
attempt left undone, step by step, each step skipped only when its effect is already established.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.config.machine import config
from teleclaude.core.integration.post_commit_maintenance import ActivationRefused, record_activation
from teleclaude.deployment import parse_version, version_cmp
from teleclaude.deployment.migration_runner import DeploymentMigrationError, committed_version
from teleclaude.deployment.release_checkout import PostureUnmet, select_release
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo, no_autostash_env
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
_FETCH_ARGUMENTS = ("--tags", "origin", "main")
_FAST_FORWARD_ARGUMENTS = ("merge", "--ff-only")
_PYPROJECT_FILENAME = "pyproject.toml"
_PROJECT_TABLE = "project"
_VERSION_KEY = "version"
_TEXT_ENCODING = "utf-8"
_USAGE = "usage: python -m teleclaude.deployment.self_update <event-file>"
_USAGE_EXIT_CODE = 2
_FAILED_EXIT_CODE = 1
_DECISION_EVENT = "self_update_decision"
_STEP_EVENT = "self_update_step"
_FAILED_EVENT = "self_update_failed"
_NO_VERSION_ERROR = "{path} declares no project version"
_NO_SERIES_ERROR = "stable self-update requires a compatibility series, and this installation declares none"
_UNKNOWN_TARGET_ERROR = "target {target!r} is not an advance this action performs"
_MISSING_TARGET_ERROR = "target {target} is not available after fetching"
_NOT_INSTALLATION_ERROR = "{root} is not the installed checkout, so it selects no release"
_RECOVERY_CONFLICT_ERROR = (
    "the checkout is at {head}, neither where the convergence left from ({from_commit}) nor its target ({target})"
)
_TARGET_UNKNOWN_ERROR = "the retained target commit {commit} is not available in this checkout"
_TARGET_VERSION_UNREADABLE_ERROR = "the release commit {commit} declares no readable project version: {error}"
_TAG_VERSION_MISMATCH_ERROR = "release {tag} names commit {commit}, which declares version {version}"
_NOT_LATER_ERROR = (
    "release {tag} (version {version}) is not a later version than the installed {installed}, "
    "so the installed source is kept"
)
_NOT_DESCENDANT_ERROR = (
    "release {tag} ({commit}) does not contain the installed source {installed}, so the installed source is kept"
)
_RECORDING_REFUSED_ERROR = (
    "the activation from {from_commit} to {to_commit} was not recorded ({reason}): {detail}; "
    "the convergence stays pending"
)
_PENDING_SCHEMA_VERSION: Literal[1] = 1
_SCHEMA_VERSION_FIELD = "schema_version"
_PENDING_NOT_A_RECORD_ERROR = "the pending convergence record is not a JSON object"
_FAST_FORWARD_CONTAINED_EVENT = "self_update_target_contained"
_PENDING_MIGRATED_EVENT = "self_update_pending_migrated"


class SkipReason(StrEnum):
    """Why an event calls for no convergence on this computer."""

    NOT_MAIN_PUSH = "not_a_push_to_main"
    NOT_PUBLISHED_RELEASE = "not_a_published_release"
    TAG_NOT_VERSION = "release_tag_is_not_a_semantic_version"
    OUTSIDE_SERIES = "release_outside_compatibility_series"


class ConvergenceStep(StrEnum):
    """The ordered steps of a convergence."""

    ADVANCE = "advance"
    RECORD = "record"
    CLEAR = "clear"


class SelfUpdateError(Exception):
    """A convergence step failed; the message is the reason the action reports."""


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


def _declared_version(text: str, source: str) -> str:
    """The project version a ``pyproject.toml`` text declares."""
    project = tomllib.loads(text).get(_PROJECT_TABLE)
    version = project.get(_VERSION_KEY) if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        raise SelfUpdateError(_NO_VERSION_ERROR.format(path=source))
    return version


def _checkout_version(root: Path) -> str:
    """The version the checkout's files declare, which is what its migrations are keyed to."""
    pyproject = root / _PYPROJECT_FILENAME
    return _declared_version(pyproject.read_text(encoding=_TEXT_ENCODING), str(pyproject))


def _upgrade_stored_pending() -> None:
    """Bring a stored unversioned record forward to the current shape before any consumer reads it.

    A current or newer-versioned record is left untouched, and a record that is neither the exact
    unversioned shape nor current is refused by the reader that follows, with its evidence intact.
    """
    if not PENDING_CONVERGENCE_PATH.exists():
        return
    stored: object = json.loads(PENDING_CONVERGENCE_PATH.read_text(encoding=_TEXT_ENCODING))
    if not isinstance(stored, dict):
        raise SelfUpdateError(_PENDING_NOT_A_RECORD_ERROR)
    if _SCHEMA_VERSION_FIELD in stored:
        return
    legacy = _PendingConvergenceV0.model_validate(stored)
    _write_pending(
        PendingConvergence(
            from_version=legacy.from_version,
            from_commit=legacy.from_commit,
            target=legacy.target,
            target_commit=None,
        )
    )
    logger.info(_PENDING_MIGRATED_EVENT, from_commit=legacy.from_commit, target=legacy.target)


def _read_pending() -> PendingConvergence | None:
    if not PENDING_CONVERGENCE_PATH.exists():
        return None
    return PendingConvergence.model_validate_json(PENDING_CONVERGENCE_PATH.read_text(encoding=_TEXT_ENCODING))


def _write_pending(pending: PendingConvergence) -> None:
    PENDING_CONVERGENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PENDING_CONVERGENCE_PATH.with_name(PENDING_CONVERGENCE_PATH.name + ".tmp")
    temporary.write_text(pending.model_dump_json(), encoding=_TEXT_ENCODING)
    temporary.replace(PENDING_CONVERGENCE_PATH)


def _clear_pending() -> None:
    PENDING_CONVERGENCE_PATH.unlink(missing_ok=True)


def _validated_target(target: str) -> str:
    """The recorded target, accepted only as the mainline ref or a release tag rebuilt from its numbers."""
    if target == _ALPHA_TARGET:
        return target
    try:
        return _tag_ref(parse_version(target))
    except ValueError as error:
        raise SelfUpdateError(_UNKNOWN_TARGET_ERROR.format(target=target)) from error


def _fast_forward_main(repo: Repo, target: str) -> None:
    """Alpha: fetch, then fast-forward main to the target unless main already contains it."""
    repo.git.fetch(*_FETCH_ARGUMENTS)
    try:
        target_commit = repo.commit(_validated_target(target))
    except (GitCommandError, ValueError) as error:
        raise SelfUpdateError(_MISSING_TARGET_ERROR.format(target=target)) from error
    if repo.is_ancestor(target_commit, repo.head.commit):
        return
    execute = cast(Callable[..., object], repo.git.execute)
    execute([GIT_EXECUTABLE, *_FAST_FORWARD_ARGUMENTS, target_commit.hexsha], env=no_autostash_env())


def _resolve_release(repo: Repo, pending: PendingConvergence) -> PendingConvergence:
    """Fetch, then retain the commit the release tag names; a retained commit is never re-resolved."""
    repo.git.fetch(*_FETCH_ARGUMENTS)
    if pending.target_commit is not None:
        try:
            repo.commit(pending.target_commit)
        except (GitCommandError, ValueError) as error:
            raise SelfUpdateError(_TARGET_UNKNOWN_ERROR.format(commit=pending.target_commit)) from error
        return pending
    try:
        target_commit = repo.commit(_validated_target(pending.target)).hexsha
    except (GitCommandError, ValueError) as error:
        raise SelfUpdateError(_MISSING_TARGET_ERROR.format(target=pending.target)) from error
    resolved = pending.model_copy(update={"target_commit": target_commit})
    _write_pending(resolved)
    return resolved


def _require_supported_transition(repo: Repo, pending: PendingConvergence) -> None:
    """Refuse, before the source moves, a release advance that is not a later version of the installed history.

    The target's version is the one its own commit declares, and it must be the version its tag names.
    Selecting the installed commit again only normalizes its posture and is always supported.
    """
    target_commit = pending.target_commit
    assert target_commit is not None
    if pending.from_commit == target_commit:
        return
    try:
        target_version = committed_version(repo, target_commit)
    except DeploymentMigrationError as error:
        raise SelfUpdateError(_TARGET_VERSION_UNREADABLE_ERROR.format(commit=target_commit, error=error)) from error
    if parse_version(target_version) != parse_version(pending.target):
        raise SelfUpdateError(
            _TAG_VERSION_MISMATCH_ERROR.format(tag=pending.target, commit=target_commit, version=target_version)
        )
    if version_cmp(pending.from_version, target_version) >= 0:
        raise SelfUpdateError(
            _NOT_LATER_ERROR.format(tag=pending.target, version=target_version, installed=pending.from_version)
        )
    if not repo.is_ancestor(repo.commit(pending.from_commit), repo.commit(target_commit)):
        raise SelfUpdateError(
            _NOT_DESCENDANT_ERROR.format(tag=pending.target, commit=target_commit, installed=pending.from_commit)
        )


def _select_release(root: Path, repo: Repo, pending: PendingConvergence) -> bool:
    """Select the retained release commit in detached HEAD; ``False`` when the target is already contained.

    A fresh attempt whose target the checkout already contains selects nothing: an older release
    announcement is not a rollback. An interrupted attempt continues only from where it left or at
    its target; any other checkout is preserved and reported. Whatever is selected is judged against
    the source and version the convergence left from, never against where the checkout now is.
    """
    target_commit = pending.target_commit
    assert target_commit is not None
    head_commit = repo.head.commit
    head = head_commit.hexsha
    if (
        head == pending.from_commit
        and head != target_commit
        and repo.is_ancestor(repo.commit(target_commit), head_commit)
    ):
        logger.info(_FAST_FORWARD_CONTAINED_EVENT, target=pending.target, head=head)
        return False
    if head not in (pending.from_commit, target_commit):
        raise SelfUpdateError(
            _RECOVERY_CONFLICT_ERROR.format(head=head, from_commit=pending.from_commit, target=target_commit)
        )
    _require_supported_transition(repo, pending)
    try:
        selected = select_release(root, target_commit)
    except PostureUnmet as unmet:
        raise SelfUpdateError(unmet.detail) from unmet
    if selected is None:
        raise SelfUpdateError(_NOT_INSTALLATION_ERROR.format(root=root))
    return True


def _record_advance(root: Path, repo: Repo, pending: PendingConvergence) -> None:
    """Record the advance as a canonical-main activation; a refused recording leaves the convergence pending.

    Actions already recorded are skipped, and an advance that owes none is recorded as exactly that.
    """
    head = repo.head.commit.hexsha
    if head == pending.from_commit:
        return
    recording = record_activation(root, ActivationRange(before_sha=pending.from_commit, after_sha=head))
    logger.info(
        _STEP_EVENT,
        step=ConvergenceStep.RECORD,
        from_commit=pending.from_commit,
        to_commit=head,
        recording=type(recording).__name__,
    )
    if isinstance(recording, ActivationRefused):
        raise SelfUpdateError(
            _RECORDING_REFUSED_ERROR.format(
                from_commit=pending.from_commit, to_commit=head, reason=recording.reason, detail=recording.detail
            )
        )


def _complete(root: Path, pending: PendingConvergence) -> None:
    """Complete a pending convergence in order, clearing it only after its last step succeeded."""
    repo = Repo(str(root))
    if config.deployment.channel is ReleaseChannel.ALPHA:
        _fast_forward_main(repo, pending.target)
    else:
        pending = _resolve_release(repo, pending)
        if not _select_release(root, repo, pending):
            _clear_pending()
            return
    _record_advance(root, repo, pending)
    _clear_pending()
    logger.info(_STEP_EVENT, step=ConvergenceStep.CLEAR, target=pending.target)


def converge(event_file: Path, root: Path) -> None:
    """Complete any unfinished convergence, then converge to the target the event calls for, if it calls for one."""
    _upgrade_stored_pending()
    pending = _read_pending()
    if pending is not None:
        _complete(root, pending)
    event = ReceivedEvent.model_validate_json(event_file.read_text(encoding=_TEXT_ENCODING))
    verdict = target_for_event(event, config.deployment.channel, config.deployment.series)
    if isinstance(verdict, SkipReason):
        logger.info(_DECISION_EVENT, event_id=event.id, event_type=event.type, outcome=verdict)
        return
    logger.info(_DECISION_EVENT, event_id=event.id, event_type=event.type, target=verdict.ref)
    pending = PendingConvergence(
        from_version=_checkout_version(root),
        from_commit=Repo(str(root)).head.commit.hexsha,
        target=verdict.ref,
        target_commit=None,
    )
    _write_pending(pending)
    _complete(root, pending)


def main(arguments: list[str] | None = None) -> int:
    """Converge this installation for the event in the given file; non-zero when a step failed."""
    setup_logging()
    operands = sys.argv[1:] if arguments is None else arguments
    if len(operands) != 1:
        print(_USAGE, file=sys.stderr)
        return _USAGE_EXIT_CODE
    try:
        converge(Path(operands[0]), Path.cwd())
    except (SelfUpdateError, GitCommandError, OSError, ValueError) as error:
        logger.error(_FAILED_EVENT, error=str(error), exc_info=True)
        print(str(error), file=sys.stderr)
        return _FAILED_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

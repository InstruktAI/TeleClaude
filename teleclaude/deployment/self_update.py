"""Channel-gated self-update: the maintenance action that converges this installation to its channel's target.

The action is handed the platform event it reacts to as a file. From the event and this computer's
deployment channel it decides whether the event calls for a target the checkout lacks. A target is
reached by advancing the checkout's main branch by fast-forward, running the installation migrations
between the version left and the version reached, and recording the advance as an ordinary
canonical-main activation, whose installation, dependency and restart steps the commit-boundary
bindings already own.

A convergence is recorded as pending before anything is fetched and cleared only after its last step
succeeded. Every run completes a pending convergence first, so a replay finishes whatever a failed
attempt left undone, step by step, each step skipped only when its effect is already established.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.config._models import ReleaseChannel
from teleclaude.config.machine import config
from teleclaude.core.integration.post_commit_maintenance import record_activation
from teleclaude.deployment import parse_version, version_cmp
from teleclaude.deployment.migration_runner import run_migrations
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
_PINNED_MINOR_SEPARATOR = "."
_PINNED_MINOR_PARTS = 2
_USAGE = "usage: python -m teleclaude.deployment.self_update <event-file>"
_USAGE_EXIT_CODE = 2
_FAILED_EXIT_CODE = 1
_DECISION_EVENT = "self_update_decision"
_STEP_EVENT = "self_update_step"
_FAILED_EVENT = "self_update_failed"
_NO_VERSION_ERROR = "{path} declares no project version"
_UNKNOWN_TARGET_ERROR = "target {target!r} is not an advance this action performs"
_MISSING_TARGET_ERROR = "target {target} is not available after fetching"
_MIGRATION_ERROR = "migrations failed: {error}"


class SkipReason(StrEnum):
    """Why an event calls for no convergence on this computer."""

    NOT_MAIN_PUSH = "not_a_push_to_main"
    NOT_PUBLISHED_RELEASE = "not_a_published_release"
    TAG_NOT_VERSION = "release_tag_is_not_a_semantic_version"
    OUTSIDE_PINNED_MINOR = "release_outside_pinned_minor"


class ConvergenceStep(StrEnum):
    """The ordered steps of a convergence."""

    ADVANCE = "advance"
    MIGRATE = "migrate"
    RECORD = "record"
    CLEAR = "clear"


class SelfUpdateError(Exception):
    """A convergence step failed; the message is the reason the action reports."""


class PendingConvergence(BaseModel):
    """A convergence that began and has not finished: where it left from and the target it advances to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_version: str
    from_commit: str
    target: str


@dataclass(frozen=True)
class ConvergenceTarget:
    """The ref a channel admits an event to converge to."""

    ref: str


def target_for_event(
    event: ReceivedEvent, channel: ReleaseChannel, pinned_minor: str
) -> ConvergenceTarget | SkipReason:
    """Decide from the event and the computer's channel whether, and to what, the installation converges."""
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
    if channel is ReleaseChannel.STABLE and not _within_pinned_minor(version, pinned_minor):
        return SkipReason.OUTSIDE_PINNED_MINOR
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


def _within_pinned_minor(version: tuple[int, int, int], pinned_minor: str) -> bool:
    """Whether a release falls within the pinned ``major.minor`` series."""
    parts = pinned_minor.split(_PINNED_MINOR_SEPARATOR)
    if len(parts) != _PINNED_MINOR_PARTS or not all(part.isdigit() for part in parts):
        return False
    return version[:_PINNED_MINOR_PARTS] == (int(parts[0]), int(parts[1]))


def _checkout_version(root: Path) -> str:
    """The version the checkout's files declare, which is what its migrations are keyed to."""
    pyproject = root / _PYPROJECT_FILENAME
    project = tomllib.loads(pyproject.read_text(encoding=_TEXT_ENCODING)).get(_PROJECT_TABLE)
    version = project.get(_VERSION_KEY) if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        raise SelfUpdateError(_NO_VERSION_ERROR.format(path=pyproject))
    return version


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


def _advance(repo: Repo, target: str) -> None:
    """Fetch, then fast-forward main to the target unless main already contains it."""
    repo.git.fetch(*_FETCH_ARGUMENTS)
    try:
        target_commit = repo.commit(_validated_target(target))
    except (GitCommandError, ValueError) as error:
        raise SelfUpdateError(_MISSING_TARGET_ERROR.format(target=target)) from error
    if repo.is_ancestor(target_commit, repo.head.commit):
        return
    execute = cast(Callable[..., object], repo.git.execute)
    execute([GIT_EXECUTABLE, *_FAST_FORWARD_ARGUMENTS, target_commit.hexsha], env=no_autostash_env())


def _migrate(root: Path, pending: PendingConvergence) -> None:
    """Run the migrations between the version the convergence left and the version the checkout now carries."""
    reached_version = _checkout_version(root)
    if version_cmp(pending.from_version, reached_version) >= 0:
        return
    result = run_migrations(pending.from_version, reached_version)
    if result["error"] is not None:
        raise SelfUpdateError(_MIGRATION_ERROR.format(error=result["error"]))
    logger.info(
        _STEP_EVENT,
        step=ConvergenceStep.MIGRATE,
        migrations_run=result["migrations_run"],
        migrations_skipped=result["migrations_skipped"],
    )


def _record_advance(root: Path, repo: Repo, pending: PendingConvergence) -> None:
    """Record the advance as a canonical-main activation; actions already recorded are skipped."""
    head = repo.head.commit.hexsha
    if head == pending.from_commit:
        return
    recorded = record_activation(root, ActivationRange(before_sha=pending.from_commit, after_sha=head))
    logger.info(
        _STEP_EVENT, step=ConvergenceStep.RECORD, from_commit=pending.from_commit, to_commit=head, recorded=recorded
    )


def _complete(root: Path, pending: PendingConvergence) -> None:
    """Complete a pending convergence in order, clearing it only after its last step succeeded."""
    repo = Repo(str(root))
    _advance(repo, pending.target)
    _migrate(root, pending)
    _record_advance(root, repo, pending)
    _clear_pending()
    logger.info(_STEP_EVENT, step=ConvergenceStep.CLEAR, target=pending.target)


def converge(event_file: Path, root: Path) -> None:
    """Complete any unfinished convergence, then converge to the target the event calls for, if it calls for one."""
    pending = _read_pending()
    if pending is not None:
        _complete(root, pending)
    event = ReceivedEvent.model_validate_json(event_file.read_text(encoding=_TEXT_ENCODING))
    verdict = target_for_event(event, config.deployment.channel, config.deployment.pinned_minor)
    if isinstance(verdict, SkipReason):
        logger.info(_DECISION_EVENT, event_id=event.id, event_type=event.type, outcome=verdict)
        return
    logger.info(_DECISION_EVENT, event_id=event.id, event_type=event.type, target=verdict.ref)
    pending = PendingConvergence(
        from_version=_checkout_version(root),
        from_commit=Repo(str(root)).head.commit.hexsha,
        target=verdict.ref,
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

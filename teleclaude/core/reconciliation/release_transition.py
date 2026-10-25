"""The forward-only rule between the active release and a target revision.

A target equal to the active revision is a no-op, decided by the caller. A target whose history
contains the active revision is admitted — for a mainline revision that is the whole condition. A
published-release target (beta or stable, or a named release tag) must also commit a version equal to
its tag and strictly later than the active release's committed version. A target the active revision
contains (older) or one on a separate history (sideways) is refused with that reason
(``local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.deployment import parse_version, version_cmp
from teleclaude.deployment.migration_runner import DeploymentMigrationError, committed_version
from teleclaude.git import BadName, GitCommandError, Repo

_VERSION_UNREADABLE = "the release commit {commit} declares no readable project version: {error}"
_TAG_VERSION_MISMATCH = "release {tag} names commit {commit}, which declares version {version}"
_NOT_LATER = (
    "release {tag} (version {version}) is not a later version than the active {active}, so the active release is kept"
)
_OLDER = "revision {target} is contained by the active release {active}, so the active release is kept"
_SIDEWAYS = "revision {target} does not contain the active release {active}, so the active release is kept"
_BASELINE_UNKNOWN = (
    "the revision the platform runs, {active}, is not in the source repository, so nothing can be said to follow it"
)


class TransitionRefusal(StrEnum):
    """Why a target revision is not an admitted forward step."""

    OLDER = "older"
    SIDEWAYS = "sideways"
    TAG_VERSION_MISMATCH = "tag_version_mismatch"
    NOT_LATER_VERSION = "not_later_version"
    VERSION_UNREADABLE = "version_unreadable"
    BASELINE_UNKNOWN = "baseline_unknown"


@dataclass(frozen=True)
class Refusal:
    """A refused transition: the typed reason and the sentence that says it."""

    reason: TransitionRefusal
    detail: str


def transition_refusal(repository: Repo, active: str, target: str, release_tag: str | None) -> Refusal | None:
    """The refusal for installing ``target`` over ``active``, or ``None`` when it is an admitted forward step.

    ``release_tag`` names the published release the target was selected as; ``None`` for a mainline revision.
    """
    try:
        active_commit = repository.commit(active)
    except (GitCommandError, BadName, ValueError):
        return Refusal(TransitionRefusal.BASELINE_UNKNOWN, _BASELINE_UNKNOWN.format(active=active))
    target_commit = repository.commit(target)
    if not repository.is_ancestor(active_commit, target_commit):
        if repository.is_ancestor(target_commit, active_commit):
            return Refusal(TransitionRefusal.OLDER, _OLDER.format(target=target, active=active))
        return Refusal(TransitionRefusal.SIDEWAYS, _SIDEWAYS.format(target=target, active=active))
    if release_tag is None:
        return None
    try:
        target_version = committed_version(repository, target)
        active_version = committed_version(repository, active)
    except DeploymentMigrationError as error:
        return Refusal(TransitionRefusal.VERSION_UNREADABLE, _VERSION_UNREADABLE.format(commit=target, error=error))
    if parse_version(target_version) != parse_version(release_tag):
        return Refusal(
            TransitionRefusal.TAG_VERSION_MISMATCH,
            _TAG_VERSION_MISMATCH.format(tag=release_tag, commit=target, version=target_version),
        )
    if version_cmp(active_version, target_version) >= 0:
        return Refusal(
            TransitionRefusal.NOT_LATER_VERSION,
            _NOT_LATER.format(tag=release_tag, version=target_version, active=active_version),
        )
    return None

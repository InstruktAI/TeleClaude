"""Installed release checkout: which checkout is the installation, and the release it selects.

A beta or stable installation runs the exact source its channel admitted: its checkout has a
detached HEAD at the release's commit, and an argument-less ``git pull`` cannot integrate
newer development commits into it. This module owns that installed-source posture for every
consumer — the channel updater, the maintenance executor, configuration migration and
publication — so none of them derives its own copy of the installation fact.

The installation is the checkout the installer-published ``telec`` executable belongs to. The
imported module location, the release channel or a detached HEAD alone identify nothing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.machine import config
from teleclaude.core.integration._maintenance_records import maintenance_drain_lock
from teleclaude.deployment import parse_version
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ConfigFileName

logger = get_logger(__name__)

_PUBLISHED_EXECUTABLE = Path(".local") / "bin" / "telec"
_EXECUTABLE_DIRECTORY = "bin"
_GIT_DIRECTORY = ".git"
_TAG_TEMPLATE = "v{major}.{minor}.{patch}"
_FETCH_CONFIG_KEY = "remote.origin.fetch"
_FETCH_GLOB = "+refs/heads/*:refs/remotes/origin/*"
_FETCH_WILDCARD = "*"
_REFS_HEADS_PREFIX = "+refs/heads/"
_REFS_REMOTES_ORIGIN_PREFIX = "refs/remotes/origin/"
_FETCH_SEPARATOR = ":"
_GIT_LOCAL_SCOPE = "--local"
_GIT_GET_ALL = "--get-all"
_GIT_REPLACE_ALL = "--replace-all"
_GIT_FIXED_VALUE = "--fixed-value"
_GIT_CHECKOUT_DETACH = "--detach"
_GIT_POINTS_AT = "--points-at"
_GIT_CONTAINS = "--contains"
_GIT_FOR_EACH_REF_FORMAT = "--format=%(refname)"
_GIT_REFS_NAMESPACE = "refs/"
_SELECTED_EVENT = "release_checkout_selected"
_NOT_APPLICABLE_EVENT = "release_checkout_not_applicable"
_UNMET_EVENT = "release_checkout_unmet"
_OBSERVED_LINE = "release {tag} {commit}"
_NOT_APPLICABLE_LINE = "no release installation here"
_NO_RELEASE_SELECTED_LINE = "no release selected yet: {detail}"
_SUPERSEDED_DETAIL = "checkout is at {actual}, not the expected {expected}"
_TAG_MISSING_DETAIL = "no release tag names commit {commit}"
_COMMIT_UNKNOWN_DETAIL = "commit {commit} is not available in this checkout: {error}"
_CHECKOUT_REFUSED_DETAIL = "git refused to select {commit} without discarding local work: {error}"
_UNPRESERVED_HEAD_DETAIL = "the detached HEAD {commit} is held by no branch or tag, so leaving it would strand its work"
_UNSUPPORTED_FETCH_DETAIL = "origin's fetch mapping {mapping} is neither the standard nor the single-branch form"
_FETCH_UPDATE_DETAIL = "origin's fetch mapping could not be normalized: {error}"
_POSTCONDITION_DETAIL = "{condition} after selecting {commit}"
_NOT_DETACHED_CONDITION = "HEAD is not detached"
_WRONG_COMMIT_CONDITION = "HEAD is not at the selected commit"
_PULLABLE_CONDITION = "origin's fetch mapping still lets an argument-less pull integrate a branch"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)
_ROOT_OPTION = "--root"
_AFTER_SHA_OPTION = "--after-sha"
_HEAD_OPTION = "--head"
_SUCCEEDED_EXIT_CODE = 0
_UNMET_EXIT_CODE = 1
_USAGE_EXIT_CODE = 2
_MODE_REQUIRED = "name the commit to normalize with --after-sha, or the checked-out one with --head"
_SERIALIZED_OPTION = "--serialized"


class PostureRefusal(StrEnum):
    """Why a checkout could not be brought to its release's detached posture."""

    SUPERSEDED = "superseded"
    TAG_MISSING = "tag_missing"
    COMMIT_UNKNOWN = "commit_unknown"
    CHECKOUT_REFUSED = "checkout_refused"
    UNPRESERVED_HEAD = "unpreserved_head"
    UNSUPPORTED_FETCH_MAPPING = "unsupported_fetch_mapping"
    FETCH_UPDATE_FAILED = "fetch_update_failed"
    POSTCONDITION_UNMET = "postcondition_unmet"


class PostureUnmet(Exception):
    """The release posture was not reached; nothing was forced and local work is intact."""

    def __init__(self, refusal: PostureRefusal, detail: str) -> None:
        super().__init__(detail)
        self.refusal = refusal
        self.detail = detail


@dataclass(frozen=True)
class SelectedRelease:
    """The release an installation selects: its tag and full commit, observable together."""

    tag: str
    commit: str


def installed_checkout_root() -> Path | None:
    """The checkout the installer-published ``telec`` executable belongs to, or ``None`` when unpublished.

    Only a primary checkout qualifies: a linked worktree carries no installation.
    """
    link = Path.home() / _PUBLISHED_EXECUTABLE
    if not link.is_symlink():
        return None
    target = link.resolve()
    if target.parent.name != _EXECUTABLE_DIRECTORY:
        return None
    root = target.parent.parent
    if not (root / _GIT_DIRECTORY).is_dir() or not (root / ConfigFileName.OVERLAY).is_file():
        return None
    return root


def is_installed_checkout(root: Path) -> bool:
    """Whether ``root`` is the checkout the published executable belongs to."""
    installed = installed_checkout_root()
    return installed is not None and root.resolve() == installed


def is_release_installation(root: Path) -> bool:
    """Whether ``root`` is the installed checkout of a beta or stable channel.

    An unreadable machine configuration raises ``ConfigLoadError``: the channel cannot be told, and
    guessing it would either grant installation effects to a checkout that has none or withhold the
    source protection from one that does.
    """
    return is_installed_checkout(root) and config.deployment.channel is not ReleaseChannel.ALPHA


def selected_revision(root: Path) -> str | None:
    """The full commit a release installation runs, or ``None`` for any other checkout.

    The answer is the checked-out commit whatever the posture, so a posture that failed or has
    not been reached yet never makes a consumer fall back to a development branch.
    """
    if not is_release_installation(root):
        return None
    return Repo(str(root.resolve())).head.commit.hexsha


def select_release(root: Path, commit: str) -> SelectedRelease | None:
    """Select ``commit`` in detached HEAD and make an ordinary pull unable to leave it.

    Returns the selected release, or ``None`` when ``root`` is not a release installation.
    Checkout is never forced: local work the transition cannot preserve refuses it.
    """
    if not is_release_installation(root):
        logger.info(_NOT_APPLICABLE_EVENT, project_root=str(root), commit=commit)
        return None
    repository = Repo(str(root.resolve()))
    _require_known_commit(repository, commit)
    return _settle_posture(repository, commit)


def normalize_posture(root: Path, expected_commit: str) -> SelectedRelease | None:
    """Detach the commit the installation already runs; move no source.

    The checkout must still be at ``expected_commit``: a superseded activation selects nothing.
    Returns ``None`` when ``root`` is not a release installation.
    """
    if not is_release_installation(root):
        logger.info(_NOT_APPLICABLE_EVENT, project_root=str(root), commit=expected_commit)
        return None
    repository = Repo(str(root.resolve()))
    actual = repository.head.commit.hexsha
    if actual != expected_commit:
        raise PostureUnmet(
            PostureRefusal.SUPERSEDED, _SUPERSEDED_DETAIL.format(actual=actual, expected=expected_commit)
        )
    return _settle_posture(repository, expected_commit)


def release_tag(repository: Repo, commit: str) -> str | None:
    """The highest canonical version tag naming ``commit``, or ``None`` when the commit is no release."""
    tagged: list[tuple[tuple[int, int, int], str]] = []
    for name in str(repository.git.tag(_GIT_POINTS_AT, commit)).split():
        try:
            version = parse_version(name)
        except ValueError:
            continue
        if _tag_name(version) == name:
            tagged.append((version, name))
    return max(tagged)[1] if tagged else None


def _tag_name(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)


def _require_known_commit(repository: Repo, commit: str) -> None:
    try:
        resolved = repository.commit(commit).hexsha
    except _GIT_FAILURES as error:
        raise PostureUnmet(
            PostureRefusal.COMMIT_UNKNOWN, _COMMIT_UNKNOWN_DETAIL.format(commit=commit, error=error)
        ) from error
    if resolved != commit:
        raise PostureUnmet(PostureRefusal.COMMIT_UNKNOWN, _COMMIT_UNKNOWN_DETAIL.format(commit=commit, error=resolved))


def _checkout_detached(repository: Repo, commit: str) -> None:
    """Detach HEAD at ``commit`` without discarding local work or stranding an unreferenced HEAD."""
    current = repository.head.commit.hexsha
    if (
        current != commit
        and repository.head.is_detached
        and not str(
            repository.git.for_each_ref(_GIT_FOR_EACH_REF_FORMAT, _GIT_CONTAINS, current, _GIT_REFS_NAMESPACE)
        ).strip()
    ):
        raise PostureUnmet(PostureRefusal.UNPRESERVED_HEAD, _UNPRESERVED_HEAD_DETAIL.format(commit=current))
    try:
        repository.git.checkout(_GIT_CHECKOUT_DETACH, commit)
    except GitCommandError as error:
        raise PostureUnmet(
            PostureRefusal.CHECKOUT_REFUSED, _CHECKOUT_REFUSED_DETAIL.format(commit=commit, error=error)
        ) from error


def _settle_posture(repository: Repo, commit: str) -> SelectedRelease:
    """Detach ``commit``, make an ordinary pull inert, and prove both."""
    tag = release_tag(repository, commit)
    if tag is None:
        raise PostureUnmet(PostureRefusal.TAG_MISSING, _TAG_MISSING_DETAIL.format(commit=commit))
    if not repository.head.is_detached or repository.head.commit.hexsha != commit:
        _checkout_detached(repository, commit)
    _normalize_fetch_mapping(repository)
    _verify_posture(repository, commit)
    logger.info(_SELECTED_EVENT, project_root=str(repository.working_tree_dir), tag=tag, commit=commit)
    return SelectedRelease(tag=tag, commit=commit)


def _fetch_mappings(repository: Repo) -> tuple[str, ...]:
    try:
        return tuple(str(repository.git.config(_GIT_GET_ALL, _FETCH_CONFIG_KEY)).splitlines())
    except GitCommandError:
        return ()


def _is_single_branch_mapping(mapping: str) -> bool:
    """The mapping a single-branch clone writes: one branch to its own remote-tracking ref."""
    if not mapping.startswith(_REFS_HEADS_PREFIX):
        return False
    source, separator, destination = mapping.removeprefix(_REFS_HEADS_PREFIX).partition(_FETCH_SEPARATOR)
    return (
        bool(separator and source)
        and _FETCH_WILDCARD not in source
        and destination == _REFS_REMOTES_ORIGIN_PREFIX + source
    )


def _normalize_fetch_mapping(repository: Repo) -> None:
    """Replace a single-branch fetch mapping with the standard one so an ordinary pull refuses.

    A detached checkout with a single-branch mapping still pulls the mapped branch; the standard
    mapping selects no branch, so Git refuses. A mapping of any other shape is the operator's and is
    left untouched.
    """
    mappings = _fetch_mappings(repository)
    if not mappings or mappings == (_FETCH_GLOB,):
        return
    if len(mappings) != 1 or not _is_single_branch_mapping(mappings[0]):
        raise PostureUnmet(
            PostureRefusal.UNSUPPORTED_FETCH_MAPPING, _UNSUPPORTED_FETCH_DETAIL.format(mapping=list(mappings))
        )
    try:
        repository.git.config(
            _GIT_LOCAL_SCOPE, _GIT_FIXED_VALUE, _GIT_REPLACE_ALL, _FETCH_CONFIG_KEY, _FETCH_GLOB, mappings[0]
        )
    except GitCommandError as error:
        raise PostureUnmet(PostureRefusal.FETCH_UPDATE_FAILED, _FETCH_UPDATE_DETAIL.format(error=error)) from error


def _verify_posture(repository: Repo, commit: str) -> None:
    if not repository.head.is_detached:
        raise PostureUnmet(
            PostureRefusal.POSTCONDITION_UNMET,
            _POSTCONDITION_DETAIL.format(condition=_NOT_DETACHED_CONDITION, commit=commit),
        )
    if repository.head.commit.hexsha != commit:
        raise PostureUnmet(
            PostureRefusal.POSTCONDITION_UNMET,
            _POSTCONDITION_DETAIL.format(condition=_WRONG_COMMIT_CONDITION, commit=commit),
        )
    mappings = _fetch_mappings(repository)
    if mappings and mappings != (_FETCH_GLOB,):
        raise PostureUnmet(
            PostureRefusal.POSTCONDITION_UNMET,
            _POSTCONDITION_DETAIL.format(condition=_PULLABLE_CONDITION, commit=commit),
        )


def _report(root: Path, run: str | None) -> int:
    """Settle the posture once, print what is observable and map the outcome to an exit status."""
    try:
        selected = normalize_posture(root, run) if run is not None else _normalize_head(root)
    except PostureUnmet as unmet:
        logger.error(_UNMET_EVENT, project_root=str(root), refusal=unmet.refusal, detail=unmet.detail)
        print(unmet.detail, file=sys.stderr)
        return _UNMET_EXIT_CODE
    except _GIT_FAILURES as error:
        logger.error(_UNMET_EVENT, project_root=str(root), detail=str(error), exc_info=True)
        print(str(error), file=sys.stderr)
        return _UNMET_EXIT_CODE
    if selected is None:
        print(_NOT_APPLICABLE_LINE)
    else:
        print(_OBSERVED_LINE.format(tag=selected.tag, commit=selected.commit))
    return _SUCCEEDED_EXIT_CODE


def _normalize_head(root: Path) -> SelectedRelease | None:
    """Normalize the commit the installation runs now; an installation that has not adopted a release yet has none."""
    if not is_release_installation(root):
        return None
    head = Repo(str(root.resolve())).head.commit.hexsha
    try:
        return normalize_posture(root, head)
    except PostureUnmet as unmet:
        if unmet.refusal is not PostureRefusal.TAG_MISSING:
            raise
        print(_NO_RELEASE_SELECTED_LINE.format(detail=unmet.detail))
        return None


def main(arguments: list[str] | None = None) -> int:
    """Normalize the installation's posture for one commit (a maintenance action) or for its HEAD (the installer).

    The HEAD form takes the checkout's maintenance serialization unless ``--serialized`` says the
    caller, a maintenance run, already holds it.
    """
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_ROOT_OPTION, type=Path, default=Path.cwd())
    parser.add_argument(_AFTER_SHA_OPTION)
    parser.add_argument(_HEAD_OPTION, action="store_true")
    parser.add_argument(_SERIALIZED_OPTION, action="store_true")
    options = parser.parse_args(sys.argv[1:] if arguments is None else arguments)
    root: Path = options.root.resolve()
    if options.after_sha is not None:
        return _report(root, options.after_sha)
    if not options.head:
        print(_MODE_REQUIRED, file=sys.stderr)
        return _USAGE_EXIT_CODE
    if options.serialized:
        return _report(root, None)
    with maintenance_drain_lock(root):
        return _report(root, None)


if __name__ == "__main__":
    raise SystemExit(main())

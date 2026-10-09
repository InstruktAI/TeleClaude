"""Read and materialize Git trees for publication and commit validation."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from teleclaude.git import GIT_EXECUTABLE, Repo, hook_free_environment
from teleclaude.paths import ConfigFileName

_GIT_LIST_INDEX_PATHS_ARGUMENTS = ("ls-files", "-z")
_GIT_LIST_COMMIT_PATHS_ARGUMENTS = ("ls-tree", "-r", "--name-only", "-z")
_GIT_SHOW_TREE_PATH_ARGUMENTS = ("show",)
_GIT_VERIFY_HEAD_ARGUMENTS = ("rev-parse", "--verify", "HEAD")
_GIT_WORKTREE_ADD_COMMIT_ARGUMENTS = ("worktree", "add", "--detach")
_GIT_WORKTREE_ADD_INDEX_ARGUMENTS = (*_GIT_WORKTREE_ADD_COMMIT_ARGUMENTS, "--no-checkout")
_GIT_WORKTREE_ADD_ORPHAN_ARGUMENTS = ("worktree", "add", "--orphan", "-b")
_GIT_WORKTREE_REMOVE_ARGUMENTS = ("worktree", "remove", "--force")
_GIT_CHECKOUT_INDEX_ARGUMENTS = ("checkout-index", "--all", "--force")
_GIT_PATH_SEPARATOR = "\0"
_GIT_PATH_SEPARATOR_BYTES = b"\0"
_GIT_PATHSPEC_SEPARATOR = "--"
_SNAPSHOT_DIRECTORY_PREFIX = "teleclaude-tree-"
_SNAPSHOT_SOURCE_DIRECTORY = "source"
_SNAPSHOT_VENV_NAME = ".venv"
_SNAPSHOT_ENVIRONMENT_MODE = 0o600
_ORPHAN_BRANCH_PREFIX = "teleclaude-index-snapshot-"
_INDEX_PATH_PREFIX = ":"
_TREE_PATH_SEPARATOR = ":"
_GIT_INDEX_FILE_ENVIRONMENT_VARIABLE = "GIT_INDEX_FILE"
_GIT_INDEX_FILE_ENVIRONMENT_PRESERVE = frozenset({_GIT_INDEX_FILE_ENVIRONMENT_VARIABLE})
_MISSING_COMMIT = "A commit tree source requires a commit id."


class TreeSourceKind(StrEnum):
    """The authoritative Git tree to read."""

    INDEX = "index"
    COMMIT = "commit"


@dataclass(frozen=True)
class TreeSource:
    """A tree source rooted in one repository."""

    repository_root: Path
    kind: TreeSourceKind
    commit: str | None = None

    @classmethod
    def active_index(cls, repository_root: Path) -> TreeSource:
        """Return the active-index source, preserving any caller index override."""
        return cls(repository_root=repository_root.expanduser().resolve(), kind=TreeSourceKind.INDEX)

    @classmethod
    def recorded_commit(cls, repository_root: Path, commit: str) -> TreeSource:
        """Return a recorded-commit source."""
        return cls(
            repository_root=repository_root.expanduser().resolve(),
            kind=TreeSourceKind.COMMIT,
            commit=commit,
        )


def tree_read_environment(
    repository_root: Path,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment for tree reads, preserving only the active index override."""
    return hook_free_environment(
        repository_root,
        base_environment=base_environment,
        preserve=_GIT_INDEX_FILE_ENVIRONMENT_PRESERVE,
    )


def list_tree_paths(source: TreeSource) -> list[str]:
    """List tracked paths in a commit or in the active index as NUL-delimited data."""
    if source.kind is TreeSourceKind.INDEX:
        arguments = [*_GIT_LIST_INDEX_PATHS_ARGUMENTS]
        environment = tree_read_environment(source.repository_root)
    else:
        if source.commit is None:
            raise ValueError(_MISSING_COMMIT)
        arguments = [*_GIT_LIST_COMMIT_PATHS_ARGUMENTS, source.commit]
        environment = hook_free_environment(source.repository_root)
    _, output, _ = _git_execute(
        source.repository_root,
        [*arguments, _GIT_PATHSPEC_SEPARATOR],
        environment,
        check=True,
        binary_output=True,
    )
    assert isinstance(output, bytes)
    return [os.fsdecode(path) for path in output.split(_GIT_PATH_SEPARATOR_BYTES) if path]


def read_tree_path(source: TreeSource, relative_path: str) -> bytes:
    """Read one path's exact bytes from a commit or the active index."""
    if source.kind is TreeSourceKind.INDEX:
        tree_path = f"{_INDEX_PATH_PREFIX}{relative_path}"
        environment = tree_read_environment(source.repository_root)
    else:
        if source.commit is None:
            raise ValueError(_MISSING_COMMIT)
        tree_path = f"{source.commit}{_TREE_PATH_SEPARATOR}{relative_path}"
        environment = hook_free_environment(source.repository_root)
    _, output, _ = _git_execute(
        source.repository_root,
        [*_GIT_SHOW_TREE_PATH_ARGUMENTS, tree_path],
        environment,
        check=True,
        binary_output=True,
    )
    assert isinstance(output, bytes)
    return output


@contextmanager
def materialize_tree(source: TreeSource) -> Iterator[Path]:
    """Materialize a Git tree as a temporary linked worktree and always remove it."""
    with tempfile.TemporaryDirectory(prefix=_SNAPSHOT_DIRECTORY_PREFIX) as temp_dir:
        snapshot_root = Path(temp_dir) / _SNAPSHOT_SOURCE_DIRECTORY
        try:
            if source.kind is TreeSourceKind.COMMIT:
                if source.commit is None:
                    raise ValueError(_MISSING_COMMIT)
                _add_recorded_worktree(source.repository_root, snapshot_root, source.commit)
            else:
                _add_index_worktree(source.repository_root, snapshot_root)
                _checkout_active_index(source.repository_root, snapshot_root)
            canonical_venv = source.repository_root / _SNAPSHOT_VENV_NAME
            if canonical_venv.exists():
                (snapshot_root / _SNAPSHOT_VENV_NAME).symlink_to(canonical_venv, target_is_directory=True)
            _copy_declaration_environments(source, snapshot_root)
            yield snapshot_root
        finally:
            _git_execute(
                source.repository_root,
                [*_GIT_WORKTREE_REMOVE_ARGUMENTS, str(snapshot_root)],
                hook_free_environment(source.repository_root),
                check=False,
            )


def _copy_declaration_environments(source: TreeSource, snapshot_root: Path) -> None:
    """Give each committed configuration declaration this computer's environment file beside it.

    Git never carries a ``.env``, so without this a snapshot's declarations would be judged as if
    no value resolved on this computer. Copies, not links: owner-only environments must stay
    regular files. The snapshot's owner-only temporary directory removes them with it.
    """
    for relative_path in list_tree_paths(source):
        declaration = Path(relative_path)
        if declaration.name != ConfigFileName.OVERLAY:
            continue
        live_environment = source.repository_root / declaration.parent / ConfigFileName.ENV
        snapshot_environment = snapshot_root / declaration.parent / ConfigFileName.ENV
        if not live_environment.is_file() or snapshot_environment.exists():
            continue
        shutil.copyfile(live_environment, snapshot_environment)
        snapshot_environment.chmod(_SNAPSHOT_ENVIRONMENT_MODE)


def _add_recorded_worktree(repository_root: Path, snapshot_root: Path, commit: str) -> None:
    """Add a detached linked worktree for a recorded commit."""
    _git_execute(
        repository_root,
        [*_GIT_WORKTREE_ADD_COMMIT_ARGUMENTS, str(snapshot_root), commit],
        hook_free_environment(repository_root),
        check=True,
    )


def _add_index_worktree(repository_root: Path, snapshot_root: Path) -> None:
    """Add a linked worktree for the active index, including unborn repositories."""
    status, head, _ = _git_execute(
        repository_root,
        list(_GIT_VERIFY_HEAD_ARGUMENTS),
        hook_free_environment(repository_root),
        check=False,
    )
    if status == 0:
        assert isinstance(head, str)
        _git_execute(
            repository_root,
            [*_GIT_WORKTREE_ADD_INDEX_ARGUMENTS, str(snapshot_root), head.strip()],
            hook_free_environment(repository_root),
            check=True,
        )
        return
    orphan_branch = f"{_ORPHAN_BRANCH_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
    _git_execute(
        repository_root,
        [*_GIT_WORKTREE_ADD_ORPHAN_ARGUMENTS, orphan_branch, str(snapshot_root)],
        hook_free_environment(repository_root),
        check=True,
    )


def _checkout_active_index(repository_root: Path, snapshot_root: Path) -> None:
    """Fill a no-checkout linked worktree from the caller's active index."""
    _git_execute(
        repository_root,
        [*_GIT_CHECKOUT_INDEX_ARGUMENTS, f"--prefix={snapshot_root}{os.sep}"],
        tree_read_environment(repository_root),
        check=True,
    )


def _git_execute(
    repository_root: Path,
    arguments: list[str],
    environment: Mapping[str, str],
    *,
    check: bool,
    binary_output: bool = False,
) -> tuple[int, bytes | str, bytes | str]:
    """Run GitPython's observed execution seam with explicit environment and argv."""
    execute = cast(Callable[..., object], Repo(str(repository_root)).git.execute)
    result = execute(
        [GIT_EXECUTABLE, *arguments],
        env=dict(environment),
        with_extended_output=True,
        with_exceptions=check,
        stdout_as_string=not binary_output,
    )
    return cast(tuple[int, bytes | str, bytes | str], result)

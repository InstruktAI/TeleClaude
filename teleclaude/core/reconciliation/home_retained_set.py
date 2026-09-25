"""Decide which paths belong to the TeleClaude home's local history."""

from __future__ import annotations

import hashlib
import os
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory

from teleclaude.git import GitCommandError, Repo
from teleclaude.paths import HOME_RETAINED_SET_PATH, REPO_ROOT, TELECLAUDE_HOME


class HomeMembership(StrEnum):
    """Closed outcomes published by the home retained-set contract."""

    RETAINED = "retained"
    NOT_RETAINED = "not-retained"
    OUTSIDE = "outside"


class HomePathKind(StrEnum):
    """Path-kind facts that membership composes with the declaration."""

    REGULAR = "regular"
    SYMBOLIC_LINK = "symbolic-link"
    FOREIGN_ROOT = "foreign-root"


_DECLARATION_FILENAME = HOME_RETAINED_SET_PATH.name
_GIT_METADATA_DIRECTORY = ".git"
_GIT_CONFIG_COUNT_KEY = "GIT_CONFIG_COUNT"
_GIT_CONFIG_KEY_TEMPLATE = "GIT_CONFIG_KEY_{count}"
_GIT_CONFIG_VALUE_TEMPLATE = "GIT_CONFIG_VALUE_{count}"
_CORE_EXCLUDES_FILE_KEY = "core.excludesFile"
_EMPTY_EXCLUDES_PATH = os.devnull
_CHECK_IGNORE_OPTION = "--no-index"
_PATH_ARGUMENT_SEPARATOR = "--"
_CHECK_IGNORE_NOT_IGNORED_STATUS = 1
_HOME_RETAINED_SET_TEMPLATE = REPO_ROOT / "templates" / "home" / "dot_gitignore"
_GIT_SYMBOLIC_LINK_MODE = "120000"
_GIT_SUBMODULE_MODE = "160000"


def home_retained_set_digest() -> str:
    """Return the stable digest that identifies the active declaration."""
    return hashlib.sha256(_HOME_RETAINED_SET_TEMPLATE.read_bytes()).hexdigest()


def home_retained_set_path(home: Path = TELECLAUDE_HOME) -> Path:
    """Return the declaration location under a particular home root."""
    return home / HOME_RETAINED_SET_PATH.name


def home_membership(path: Path, *, home: Path = TELECLAUDE_HOME) -> HomeMembership:
    """Return the retained-set membership for ``path`` without reading its content."""
    try:
        canonical_home = home.expanduser().resolve()
    except (OSError, RuntimeError):
        return HomeMembership.NOT_RETAINED
    canonical_path = _canonical_path(path, home=canonical_home)
    if canonical_path is None:
        return HomeMembership.NOT_RETAINED
    if not _is_within(canonical_path, canonical_home):
        return HomeMembership.OUTSIDE
    return _membership(canonical_path, home=canonical_home, kind=_live_path_kind(canonical_path, home=canonical_home))


def historical_home_membership(path: Path, *, mode: str, home: Path = TELECLAUDE_HOME) -> HomeMembership:
    """Return membership for a path and mode recorded in a reachable Git tree."""
    try:
        canonical_home = home.expanduser().resolve()
    except (OSError, RuntimeError):
        return HomeMembership.NOT_RETAINED
    canonical_path = _historical_canonical_path(path, home=canonical_home)
    if canonical_path is None:
        return HomeMembership.NOT_RETAINED
    return _membership(canonical_path, home=canonical_home, kind=_historical_path_kind(mode))


def _canonical_path(path: Path, *, home: Path) -> Path | None:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = home / candidate
    normalized = Path(os.path.normpath(str(candidate)))
    try:
        return normalized.parent.resolve(strict=False) / normalized.name
    except (OSError, RuntimeError):
        return None


def _historical_canonical_path(path: Path, *, home: Path) -> Path | None:
    candidate = path.expanduser()
    if candidate.is_absolute():
        return None
    normalized = Path(os.path.normpath(str(candidate)))
    if normalized == Path(".") or normalized.is_absolute() or ".." in normalized.parts:
        return None
    return home / normalized


def _is_within(path: Path, home: Path) -> bool:
    try:
        path.relative_to(home)
    except ValueError:
        return False
    return True


def _membership(path: Path, *, home: Path, kind: HomePathKind) -> HomeMembership:
    if not _is_within(path, home):
        return HomeMembership.OUTSIDE
    if kind is not HomePathKind.REGULAR:
        return HomeMembership.NOT_RETAINED
    return _declaration_membership(path.relative_to(home))


def _live_path_kind(path: Path, *, home: Path) -> HomePathKind:
    if _has_foreign_root(path, home=home):
        return HomePathKind.FOREIGN_ROOT
    if _is_symbolic_link(path):
        return HomePathKind.SYMBOLIC_LINK
    return HomePathKind.REGULAR


def _historical_path_kind(mode: str) -> HomePathKind:
    if mode == _GIT_SYMBOLIC_LINK_MODE:
        return HomePathKind.SYMBOLIC_LINK
    if mode == _GIT_SUBMODULE_MODE:
        return HomePathKind.FOREIGN_ROOT
    return HomePathKind.REGULAR


def _has_foreign_root(path: Path, *, home: Path) -> bool:
    relative_path = path.relative_to(home)
    ancestor = home
    for component in relative_path.parts[:-1]:
        ancestor /= component
        if os.path.lexists(ancestor / _GIT_METADATA_DIRECTORY):
            return True
    return bool(relative_path.parts) and os.path.lexists(path / _GIT_METADATA_DIRECTORY)


def _is_symbolic_link(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return True


def _declaration_membership(relative_path: Path) -> HomeMembership:
    relative_name = relative_path.as_posix()
    with TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        declaration_path = scratch_path / _DECLARATION_FILENAME
        declaration_path.write_bytes(_HOME_RETAINED_SET_TEMPLATE.read_bytes())
        repository = Repo.init(scratch_path)
        try:
            repository.git.check_ignore(
                _CHECK_IGNORE_OPTION,
                _PATH_ARGUMENT_SEPARATOR,
                relative_name,
                env=_isolated_git_environment(),
            )
        except GitCommandError as error:
            if error.status == _CHECK_IGNORE_NOT_IGNORED_STATUS:
                return HomeMembership.RETAINED
    return HomeMembership.NOT_RETAINED


def _isolated_git_environment() -> dict[str, str]:
    environment = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    count = int(environment.get(_GIT_CONFIG_COUNT_KEY, "0"))
    environment[_GIT_CONFIG_KEY_TEMPLATE.format(count=count)] = _CORE_EXCLUDES_FILE_KEY
    environment[_GIT_CONFIG_VALUE_TEMPLATE.format(count=count)] = _EMPTY_EXCLUDES_PATH
    environment[_GIT_CONFIG_COUNT_KEY] = str(count + 1)
    return environment

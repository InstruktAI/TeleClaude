"""Provision and retire tracked home clones owned by slug worktrees."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.worktree_layout import WORKTREE_HOMES_DIR
from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import TELECLAUDE_HOME
from teleclaude.project_root import worktree_home_root
from teleclaude.slug import validate_slug

logger = get_logger(__name__)

_GIT_HEAD = "HEAD"
_GIT_ORIGIN = "origin"
_GIT_LS_FILES_NULL = ("-z",)
_GIT_LS_TREE_ARGS = ("-r", "--name-only", "-z", _GIT_HEAD)
_GIT_ADD_ALL = "--all"
_NULL = "\0"
_DOT = "."
_PARENT = ".."
_ASCII_ENCODING = "ascii"
_BYTE_ORDER: Literal["big"] = "big"
_JSON_ENCODING = "utf-8"
_BINARY_READ_MODE = "rb"
_JSON_VERSION = "version"
_JSON_DIGEST = "digest"
_STATE_SUFFIX = ".json"
_STATE_TEMP_SUFFIX = ".tmp"
_BUILDING_DIR = ".building"
_RETIRING_DIR = ".retiring"
_GLOBAL_HOME_LOCK = ".provisioning.lock"
_LOCK_OPEN_MODE = "a"
_LOCK_EXCLUSIVE = fcntl.LOCK_EX
_LOCK_UNLOCK = fcntl.LOCK_UN
_STATE_VERSION = 1
_NAME_SEPARATOR = "-"
_WORKTREE_HOME_ERROR = "not a slug worktree: %s"
_WORKTREE_HOME_ROOT_ESCAPE_ERROR = "worktree home root is not a project-owned directory: %s"
_HOME_RELEASE_ERROR = "worktree home release failed for %s"
_UNSAFE_TRACKED_PATH_ERROR = "unsafe tracked path in home source: %r"
_SYMLINKED_PARENT_ERROR = "tracked path crosses a symlinked parent: %s"
_UNSAFE_SYMLINK_TARGET_ERROR = "tracked symlink resolves outside the home source: %s"
_SOURCE_REPOSITORY_ERROR = "home source is not a readable Git repository: %s"
_CLONE_MISMATCH_ERROR = "home clone differs from source snapshot: %s"
_PROVISIONING_ERROR = "worktree home provisioning failed for %s"
_DESTINATION_CONFLICT_ERROR = "worktree home destination already exists: %s"
_HOMES_ROOT_RECONCILE_REFUSED = "worktree home reconciliation refused"
_DIGEST_SEPARATOR = b"\0"
_LENGTH_WIDTH = 8
_EMPTY_BYTES = b""
_READ_CHUNK_SIZE = 1024 * 1024
_DELETED_MARKER = b"D"
_SYMLINK_MARKER = b"L"
_FILE_MARKER = b"F"
_EXECUTABLE_MARKER = b"X"
_NON_EXECUTABLE_MARKER = b"x"
_CLONE_NO_HARDLINKS = "--no-hardlinks"
_LOG_REMOVAL_FAILED = "orphaned worktree home cleanup failed"
_LOG_RECONCILE_FAILED = "worktree home reconciliation failed"
_LOG_PROVISIONED = "worktree home provisioned"
_LOG_RELEASED = "worktree home released"
_PROCESS_HOME_LOCK = Lock()


class WorktreeHomeError(Exception):
    """Base error for worktree home operations."""


class WorktreeHomeSourceError(WorktreeHomeError):
    """The configured home source is not a readable Git working tree."""


class WorktreeHomeValidationError(WorktreeHomeError):
    """The temporary clone does not match the source snapshot."""


class WorktreeHomeCleanupError(WorktreeHomeError):
    """An expected filesystem failure prevented home cleanup."""


@contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Coordinate home mutations with other TeleClaude processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_OPEN_MODE, encoding=_JSON_ENCODING) as lock_file:
        fcntl.flock(lock_file.fileno(), _LOCK_EXCLUSIVE)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), _LOCK_UNLOCK)


@contextmanager
def _home_operation_lock(homes_root: Path) -> Iterator[None]:
    """Serialize home mutations in this process and across processes."""
    with _PROCESS_HOME_LOCK:
        with _file_lock(homes_root / _GLOBAL_HOME_LOCK):
            yield


def _project_homes_root(project_root: Path) -> Path:
    worktrees_root = project_root / WORKTREE_DIR
    homes_root = worktrees_root / WORKTREE_HOMES_DIR
    if (
        worktrees_root.is_symlink()
        or homes_root.is_symlink()
        or not homes_root.resolve().is_relative_to(worktrees_root.resolve())
    ):
        raise WorktreeHomeError(_WORKTREE_HOME_ROOT_ESCAPE_ERROR % homes_root)
    return homes_root


def _worktree_paths(project_root: Path, slug: str) -> tuple[Path, Path]:
    validate_slug(slug)
    worktree_root = project_root / WORKTREE_DIR / slug
    home_root = worktree_home_root(worktree_root)
    if home_root is None:
        raise ValueError(_WORKTREE_HOME_ERROR % worktree_root)
    _project_homes_root(project_root)
    return worktree_root, home_root


def _record_path(home_root: Path) -> Path:
    return home_root.with_name(f"{home_root.name}{_STATE_SUFFIX}")


def _tracked_paths(repository: Repo) -> list[str]:
    index_paths = repository.git.ls_files(*_GIT_LS_FILES_NULL).split(_NULL)
    head_paths = repository.git.ls_tree(*_GIT_LS_TREE_ARGS).split(_NULL)
    return sorted({path for path in (*index_paths, *head_paths) if path})


def _relative_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or _DOT in path.parts or _PARENT in path.parts:
        raise WorktreeHomeSourceError(_UNSAFE_TRACKED_PATH_ERROR % relative)
    return root / path


def _assert_safe_parents(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    relative = path.relative_to(root)
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink() or not parent.resolve().is_relative_to(resolved_root):
            raise WorktreeHomeSourceError(_SYMLINKED_PARENT_ERROR % path)


def _digest_working_tree(repository: Repo, root: Path) -> str:
    digest = hashlib.sha256()
    head = repository.head.commit.hexsha
    digest.update(head.encode(_ASCII_ENCODING))
    digest.update(_DIGEST_SEPARATOR)

    for relative in _tracked_paths(repository):
        path = _relative_path(root, relative)
        _assert_safe_parents(root, path)
        encoded_path = os.fsencode(relative)
        digest.update(len(encoded_path).to_bytes(_LENGTH_WIDTH, _BYTE_ORDER))
        digest.update(encoded_path)
        digest.update(_DIGEST_SEPARATOR)

        if path.is_symlink():
            target = os.readlink(path)
            resolved_target = (path.parent / target).resolve(strict=False)
            if Path(target).is_absolute() or not resolved_target.is_relative_to(root.resolve()):
                raise WorktreeHomeSourceError(_UNSAFE_SYMLINK_TARGET_ERROR % path)
            encoded_target = os.fsencode(target)
            digest.update(_SYMLINK_MARKER)
            digest.update(len(encoded_target).to_bytes(_LENGTH_WIDTH, _BYTE_ORDER))
            digest.update(encoded_target)
        elif not path.is_file():
            digest.update(_DELETED_MARKER)
        else:
            mode = path.stat().st_mode
            digest.update(_FILE_MARKER)
            digest.update(
                _EXECUTABLE_MARKER if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) else _NON_EXECUTABLE_MARKER
            )
            digest.update(path.stat().st_size.to_bytes(_LENGTH_WIDTH, _BYTE_ORDER))
            with path.open(_BINARY_READ_MODE) as source_file:
                for chunk in iter(lambda: source_file.read(_READ_CHUNK_SIZE), _EMPTY_BYTES):
                    digest.update(chunk)
        digest.update(_DIGEST_SEPARATOR)
    return digest.hexdigest()


def _source_snapshot(source_root: Path) -> tuple[Repo, str]:
    try:
        repository = Repo(str(source_root))
        digest = _digest_working_tree(repository, source_root)
    except (BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError) as exc:
        raise WorktreeHomeSourceError(_SOURCE_REPOSITORY_ERROR % source_root) from exc
    return repository, digest


def _read_state(record_path: Path) -> str | None:
    if record_path.is_symlink():
        return None
    try:
        payload = json.loads(record_path.read_text(encoding=_JSON_ENCODING))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get(_JSON_VERSION)
    digest = payload.get(_JSON_DIGEST)
    if isinstance(version, bool) or version != _STATE_VERSION or not isinstance(digest, str) or not digest:
        return None
    return digest


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _mirror_tracked_worktree(source_root: Path, destination_root: Path, repository: Repo) -> None:
    for relative in _tracked_paths(repository):
        source = _relative_path(source_root, relative)
        destination = _relative_path(destination_root, relative)
        _assert_safe_parents(source_root, source)
        _assert_safe_parents(destination_root, destination)
        if not source.is_symlink() and not source.is_file():
            _remove_path(destination)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        _remove_path(destination)
        if source.is_symlink():
            destination.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, destination)

    destination_repository = Repo(str(destination_root))
    destination_repository.git.add(_GIT_ADD_ALL)


def _write_state(record_path: Path, digest: str) -> None:
    temporary_path = record_path.with_name(f"{record_path.name}{_NAME_SEPARATOR}{uuid4().hex}{_STATE_TEMP_SUFFIX}")
    payload = {_JSON_VERSION: _STATE_VERSION, _JSON_DIGEST: digest}
    try:
        temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding=_JSON_ENCODING)
        os.replace(temporary_path, record_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _build_home(source_root: Path, build_root: Path, source_repository: Repo) -> Repo:
    build_repository = Repo.clone_from(
        str(source_root),
        str(build_root),
        multi_options=[_CLONE_NO_HARDLINKS],
    )
    build_repository.delete_remote(build_repository.remote(_GIT_ORIGIN))
    _mirror_tracked_worktree(source_root, build_root, source_repository)
    return build_repository


def _ensure_worktree_home_locked(
    home_root: Path,
    slug: str,
    source_root: Path,
    source_repository: Repo,
    source_digest: str,
) -> Path:
    record_path = _record_path(home_root)
    if home_root.is_dir() and not home_root.is_symlink() and _read_state(record_path) == source_digest:
        return home_root

    homes_root = home_root.parent
    building_root = homes_root / _BUILDING_DIR
    retiring_root = homes_root / _RETIRING_DIR
    building_root.mkdir(parents=True, exist_ok=True)
    retiring_root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    build_root = building_root / f"{slug}{_NAME_SEPARATOR}{token}"
    retiring_home = retiring_root / f"{slug}{_NAME_SEPARATOR}{token}"

    try:
        build_repository = _build_home(source_root, build_root, source_repository)
        build_digest = _digest_working_tree(build_repository, build_root)
        current_source_digest = _digest_working_tree(source_repository, source_root)
        if build_digest != source_digest or current_source_digest != source_digest:
            raise WorktreeHomeValidationError(_CLONE_MISMATCH_ERROR % source_root)

        if home_root.is_dir() and not home_root.is_symlink() and _read_state(record_path) == source_digest:
            _remove_path(build_root)
            return home_root

        had_previous_home = home_root.exists() or home_root.is_symlink()
        if had_previous_home:
            os.replace(home_root, retiring_home)
        try:
            os.replace(build_root, home_root)
        except OSError:
            if had_previous_home and retiring_home.exists():
                os.replace(retiring_home, home_root)
            raise
        if had_previous_home:
            _remove_path(retiring_home)
        _write_state(record_path, source_digest)
        logger.info(_LOG_PROVISIONED, slug=slug, home=str(home_root), digest=source_digest)
        return home_root
    except WorktreeHomeError:
        _remove_path(build_root)
        raise
    except (GitCommandError, OSError, ValueError) as exc:
        _remove_path(build_root)
        raise WorktreeHomeError(_PROVISIONING_ERROR % slug) from exc


def ensure_worktree_home(project_root: Path, slug: str) -> Path:
    """Create or refresh the slug's no-remote clone from the live home source."""
    _, home_root = _worktree_paths(project_root, slug)
    source_root = TELECLAUDE_HOME
    source_repository, source_digest = _source_snapshot(source_root)
    with _home_operation_lock(home_root.parent):
        return _ensure_worktree_home_locked(home_root, slug, source_root, source_repository, source_digest)


def release_worktree_home(project_root: Path, slug: str) -> None:
    """Delete a slug-keyed worktree home and its digest record."""
    try:
        _, home_root = _worktree_paths(project_root, slug)
        with _home_operation_lock(home_root.parent):
            _remove_path(home_root)
            _record_path(home_root).unlink(missing_ok=True)
    except OSError as exc:
        raise WorktreeHomeCleanupError(_HOME_RELEASE_ERROR % slug) from exc
    logger.info(_LOG_RELEASED, slug=slug, home=str(home_root))


def move_worktree_home(project_root: Path, old_slug: str, new_slug: str) -> bool:
    """Move a slug-keyed home and its record, refusing occupied destinations."""
    _, old_home = _worktree_paths(project_root, old_slug)
    _, new_home = _worktree_paths(project_root, new_slug)
    old_record = _record_path(old_home)
    new_record = _record_path(new_home)
    with _home_operation_lock(old_home.parent):
        if new_home.exists() or new_home.is_symlink() or new_record.exists():
            raise FileExistsError(_DESTINATION_CONFLICT_ERROR % new_home)
        if not (old_home.exists() or old_home.is_symlink() or old_record.exists()):
            return False

        moved_home = False
        if old_home.exists() or old_home.is_symlink():
            os.replace(old_home, new_home)
            moved_home = True
        try:
            if old_record.exists():
                os.replace(old_record, new_record)
        except OSError:
            if moved_home and (new_home.exists() or new_home.is_symlink()):
                os.replace(new_home, old_home)
            raise
        return True


def _slug_directories(root: Path, *, include_symlinks: bool = False) -> dict[str, Path]:
    children = tuple(root.iterdir())
    slugs: dict[str, Path] = {}
    for child in children:
        try:
            validate_slug(child.name)
        except ValueError:
            continue
        mode = child.lstat().st_mode
        if (include_symlinks and stat.S_ISLNK(mode)) or stat.S_ISDIR(mode):
            slugs[child.name] = child
    return slugs


def _clear_startup_leftovers(homes_root: Path) -> None:
    directories = tuple(homes_root / name for name in (_BUILDING_DIR, _RETIRING_DIR))
    if not any(directory.is_symlink() or directory.exists() for directory in directories):
        return
    try:
        with _home_operation_lock(homes_root):
            for directory in directories:
                try:
                    _remove_path(directory)
                except OSError as exc:
                    logger.warning(_LOG_REMOVAL_FAILED, path=str(directory), error=str(exc))
    except OSError as exc:
        logger.warning(_LOG_REMOVAL_FAILED, path=str(homes_root), error=str(exc))


def reconcile_worktree_homes(project_root: Path, *, at_startup: bool) -> None:
    """Remove orphaned homes and ensure every live slug worktree has one."""
    worktrees_root = project_root / WORKTREE_DIR
    try:
        homes_root = _project_homes_root(project_root)
    except (OSError, WorktreeHomeError) as exc:
        logger.warning(_HOMES_ROOT_RECONCILE_REFUSED, path=str(worktrees_root), error=str(exc))
        return
    if at_startup:
        _clear_startup_leftovers(homes_root)

    try:
        worktrees = _slug_directories(worktrees_root)
        homes = _slug_directories(homes_root, include_symlinks=True)
        record_paths = tuple(path for path in homes_root.iterdir() if path.name.endswith(_STATE_SUFFIX))
        records: dict[str, Path] = {}
        for path in record_paths:
            slug = path.name[: -len(_STATE_SUFFIX)]
            try:
                validate_slug(slug)
            except ValueError:
                continue
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                records[slug] = path
    except OSError as exc:
        logger.warning(_LOG_RECONCILE_FAILED, project_root=str(project_root), error=str(exc))
        return
    known_slugs = set(homes) | set(records)

    for slug in sorted(known_slugs - set(worktrees)):
        try:
            release_worktree_home(project_root, slug)
        except OSError as exc:
            logger.warning(_LOG_REMOVAL_FAILED, slug=slug, error=str(exc))

    for slug in sorted(worktrees):
        if slug in homes and slug in records and _read_state(records[slug]) is not None:
            continue
        try:
            ensure_worktree_home(project_root, slug)
        except (OSError, ValueError, WorktreeHomeError) as exc:
            logger.warning(_LOG_RECONCILE_FAILED, slug=slug, error=str(exc))

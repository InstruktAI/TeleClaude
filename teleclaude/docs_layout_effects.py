"""Filesystem and index effects of documentation layout convergence, and their reversal.

A ``PerformedEffects`` record holds what a run has actually done to a repository,
entered as each effect lands and never as it is planned. ``apply_moves`` and
``stage_paths`` land effects into it; ``restore_own_changes`` undoes exactly
that record and leaves anything another writer changed where and as found.
``teleclaude.docs_layout`` decides what to move and rewrite and orchestrates the
run; this module owns how the effects land and how they come back.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from teleclaude.git import Repo

PATHSPEC_SEPARATOR: Final = "--"
_LS_FILES_STAGE_ARGS: Final = ("-s", "-z")
_RESET_ARGS: Final = ("-q",)
_INDEX_ENTRY_SEPARATOR: Final = "\t"
_NUL_SEPARATOR: Final = "\0"
_GLOB_ALL: Final = "*"

Moves = Sequence[tuple[PurePosixPath, PurePosixPath]]


@dataclass(frozen=True)
class MovedFile:
    """One file a move relocates: where it came from and the bytes it had before the run."""

    retired_path: str
    digest: str


@dataclass
class PerformedEffects:
    """What one convergence run has done to a repository so far, entered as each effect lands.

    ``moves`` are the directory renames that returned, ``moved`` their files keyed by
    new path, ``directories`` the retired directories they emptied, ``written`` the
    rewrites keyed by the path written, ``staged`` the paths ``git add`` returned for,
    and ``index_snapshots`` the index entries the run observed.
    """

    moves: list[tuple[PurePosixPath, PurePosixPath]] = field(default_factory=list)
    moved: dict[str, MovedFile] = field(default_factory=dict)
    directories: list[str] = field(default_factory=list)
    written: dict[str, tuple[bytes, bytes]] = field(default_factory=dict)
    staged: list[str] = field(default_factory=list)
    index_snapshots: list[dict[str, str]] = field(default_factory=list)


def split_nul(output: str) -> list[str]:
    """Split NUL-terminated git output into its non-empty entries."""
    return [entry for entry in output.split(_NUL_SEPARATOR) if entry]


def index_entries(repository: Repo, paths: Sequence[str]) -> dict[str, str]:
    """Return the staged ``mode object stage`` metadata of each path the index holds."""
    if not paths:
        return {}
    output = repository.git.ls_files(*_LS_FILES_STAGE_ARGS, PATHSPEC_SEPARATOR, *paths)
    entries: dict[str, str] = {}
    for entry in split_nul(output):
        metadata, path = entry.split(_INDEX_ENTRY_SEPARATOR, 1)
        entries[path] = metadata
    return entries


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inventory_move(
    root: Path, retired: PurePosixPath, target: PurePosixPath
) -> tuple[dict[str, MovedFile], list[str]]:
    """List every file and directory one move will relocate, files keyed by their new path."""
    files: dict[str, MovedFile] = {}
    retired_dir = root / retired
    directories = [str(retired)]
    for path in sorted(retired_dir.rglob(_GLOB_ALL)):
        relative = path.relative_to(retired_dir)
        if path.is_dir() and not path.is_symlink():
            directories.append(str(retired / relative))
            continue
        files[str(target / relative)] = MovedFile(
            retired_path=str(retired / relative), digest=_digest(path.read_bytes())
        )
    return files, directories


def apply_moves(root: Path, moves: Moves, performed: PerformedEffects) -> None:
    """Rename each retired directory on the filesystem, leaving the index to the commit.

    A directory enters ``performed`` only once its rename has returned, so a rename
    that fails records nothing for that directory. The move is not staged as a
    rename: the sealed commit admits a declared path only when it carries a change
    git will record, and a staged rename hides its old side. Left unstaged, the old
    paths read as deleted and the new ones as added, and the commit records them as
    renames.
    """
    for retired, target in moves:
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        files, directories = _inventory_move(root, retired, target)
        os.rename(root / retired, root / target)
        performed.moves.append((retired, target))
        performed.moved.update(files)
        performed.directories.extend(directories)


def stage_paths(repository: Repo, paths: Sequence[str], performed: PerformedEffects) -> None:
    """Stage ``paths``; they enter ``performed`` only once ``git add`` has returned."""
    repository.git.add(PATHSPEC_SEPARATOR, *paths)
    performed.staged.extend(paths)


def _prune_empty_directories(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob(_GLOB_ALL), key=lambda candidate: len(candidate.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if not any(directory.iterdir()):
        directory.rmdir()


def _changed_index_paths(
    repository: Repo, observed: Sequence[str], index_snapshots: Sequence[dict[str, str]]
) -> set[str]:
    """Observed paths whose index entry equals none this run observed: another writer staged them."""
    current_index = index_entries(repository, observed)
    return {
        path
        for path in observed
        if not any(current_index.get(path) == snapshot.get(path) for snapshot in index_snapshots)
    }


def _own_paths(performed: PerformedEffects) -> list[str]:
    """Every path this run moved (both addresses), wrote or staged."""
    retired = (record.retired_path for record in performed.moved.values())
    return sorted({*performed.moved, *retired, *performed.written, *performed.staged})


def _restore_conflicts(performed: PerformedEffects, root: Path, changed_index: set[str]) -> set[str]:
    """Establish, before anything is mutated, every path restoration must leave as found.

    A file conflicts when it is gone from the address this run left it at, when its
    bytes are not the ones this run left, when its original path is occupied again,
    or when the index entry of its current or original path was changed by another
    writer.
    """
    conflicts: set[str] = set()
    for written_path, (_, rewritten) in performed.written.items():
        if written_path in performed.moved:
            continue
        written_file = root / written_path
        if not written_file.is_file() or written_file.read_bytes() != rewritten or written_path in changed_index:
            conflicts.add(written_path)
    for new_path, record in performed.moved.items():
        current = root / new_path
        if not current.exists() and not current.is_symlink():
            conflicts.add(new_path)
            continue
        expected = performed.written.get(new_path)
        current_bytes = current.read_bytes()
        bytes_unchanged = (
            current_bytes == expected[1] if expected is not None else _digest(current_bytes) == record.digest
        )
        destination = root / record.retired_path
        if (
            not bytes_unchanged
            or destination.exists()
            or destination.is_symlink()
            or new_path in changed_index
            or record.retired_path in changed_index
        ):
            conflicts.add(new_path)
    return conflicts


def _restore_files(performed: PerformedEffects, root: Path, conflicts: set[str]) -> list[str]:
    """Move this run's own files back one by one, skipping every established conflict.

    Returns the conflicts plus any file under a directory this run moved that this
    run did not move there. A preserved file keeps its bytes and address: moving
    files individually means it is never relocated by restoring its directory.
    """
    left: list[str] = sorted(conflicts)
    for written_path, (original, _) in performed.written.items():
        if written_path in performed.moved or written_path in conflicts:
            continue
        (root / written_path).write_bytes(original)
    for relative in performed.directories:
        (root / relative).mkdir(parents=True, exist_ok=True)
    for new_path, record in performed.moved.items():
        current = root / new_path
        if new_path in conflicts or (not current.exists() and not current.is_symlink()):
            continue
        expected = performed.written.get(new_path)
        if expected is not None:
            current.write_bytes(expected[0])
        os.rename(current, root / record.retired_path)
    for _, target in performed.moves:
        target_dir = root / target
        if target_dir.is_dir():
            left.extend(
                str(path.relative_to(root))
                for path in sorted(target_dir.rglob(_GLOB_ALL))
                if not path.is_dir() and str(path.relative_to(root)) not in performed.moved
            )
            _prune_empty_directories(target_dir)
    return left


def restore_own_changes(root: Path, repository: Repo, performed: PerformedEffects) -> tuple[str, ...]:
    """Reverse only convergence's own delta; return the paths left as found.

    Only what ``performed`` records is touched. Every conflict is established
    before anything is mutated. A conflicting file keeps its bytes, its address
    and the index entries of both its current and its original path; every path
    this run staged is reset to the committed entry only when its entry still
    equals one this run observed. A run that performed nothing restores and names
    nothing.
    """
    changed_index = _changed_index_paths(repository, _own_paths(performed), performed.index_snapshots)
    conflicts = _restore_conflicts(performed, root, changed_index)
    protected = (
        set(changed_index)
        | conflicts
        | {performed.moved[path].retired_path for path in conflicts if path in performed.moved}
    )
    left = _restore_files(performed, root, conflicts)
    restorable = [path for path in performed.staged if path not in protected]
    if restorable:
        repository.git.reset(*_RESET_ARGS, PATHSPEC_SEPARATOR, *restorable)
    return tuple(sorted(set(left) | changed_index))

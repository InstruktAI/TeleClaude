"""Read-only Git evidence that identifies a marker-reconciliation fold.

Blob identity, committed tree entries, index stages, and whether a dirty path still holds exactly
its own uncommitted fold. The transaction in ``marker_reconciliation`` decides what to do with the evidence.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.next_machine.delivery import _run_git_cmd
from teleclaude.docs_reconcile import ReconciliationWrite

GIT_HASH_OBJECT_ARGS = ("hash-object",)
GIT_LS_TREE_ARGS = ("ls-tree", "-z")
GIT_LS_FILES_STAGE_ARGS = ("ls-files", "--stage", "--")
GIT_PATH_OPTION_TEMPLATE = "--path={relative_path}"
GIT_TREE_FIELD_SEPARATOR = "\t"
GIT_TREE_RECORD_SEPARATOR = "\0"
GIT_INDEX_STAGE_SEPARATOR = "\t"
GIT_BLOB_OBJECT_TYPE = "blob"
UTF8_ENCODING = "utf-8"
EMPTY_ERROR = ""
DEFAULT_FILE_MODE = "100644"
EXECUTABLE_FILE_MODE = "100755"
SYMLINK_FILE_MODE = "120000"
INDEX_STAGE_ZERO = "0"
MALFORMED_INDEX_ENTRY_REASON = "malformed_index_entry"
COMMIT_PATH_NOT_BLOB_REASON = "commit path did not resolve to a blob"
COMMIT_PATH_MULTIPLE_ENTRIES_REASON = "commit path resolved to multiple tree entries"


@dataclass(frozen=True)
class GitTreeEntry:
    """One regular Git tree entry's mode and blob identity."""

    mode: str
    blob: str


@dataclass(frozen=True)
class FoldResidue:
    """Evidence that one dirty path contains only its own uncommitted fold."""

    write: ReconciliationWrite
    head_entry: GitTreeEntry | None
    fold_blob: str | None
    expected_mode: str
    file_mode_enabled: bool
    formatted_blob: str | None = None


def expected_blob_id(
    project_root: Path,
    relative_path: str,
    content: str,
    temporary_root: Path,
    index: int,
) -> tuple[str | None, str]:
    """Hash rendered bytes using the clean filter selected for their Git path."""
    temporary_file = temporary_root / str(index)
    try:
        temporary_file.write_bytes(content.encode(UTF8_ENCODING))
    except OSError as write_error:
        return None, str(write_error)
    code, output, error = _run_git_cmd(
        [*GIT_HASH_OBJECT_ARGS, GIT_PATH_OPTION_TEMPLATE.format(relative_path=relative_path), str(temporary_file)],
        cwd=str(project_root),
    )
    if code != 0:
        return None, error
    return output.strip(), ""


def tree_entry_at_commit(
    project_root: Path,
    commit: str,
    relative_path: str,
) -> tuple[GitTreeEntry | None, str]:
    """Read one exact path's mode and blob identity from a commit tree."""
    code, output, error = _run_git_cmd([*GIT_LS_TREE_ARGS, commit, "--", relative_path], cwd=str(project_root))
    if code != 0:
        return None, error
    entries: list[GitTreeEntry] = []
    for record in output.split(GIT_TREE_RECORD_SEPARATOR):
        metadata, separator, path = record.partition(GIT_TREE_FIELD_SEPARATOR)
        if not separator or path != relative_path:
            continue
        fields = metadata.split()
        if len(fields) != 3 or fields[1] != GIT_BLOB_OBJECT_TYPE:
            return None, COMMIT_PATH_NOT_BLOB_REASON
        entries.append(GitTreeEntry(mode=fields[0], blob=fields[2]))
    if len(entries) > 1:
        return None, COMMIT_PATH_MULTIPLE_ENTRIES_REASON
    return (entries[0] if entries else None), EMPTY_ERROR


def _index_entries(project_root: Path, relative_path: str) -> tuple[list[tuple[str, str, str]] | None, str]:
    """Read every index stage for one exact path."""
    code, output, error = _run_git_cmd(
        [*GIT_LS_FILES_STAGE_ARGS, relative_path], cwd=str(project_root), preserve_stdout_newlines=True
    )
    if code != 0:
        return None, error
    entries: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        metadata, separator, path = line.partition(GIT_INDEX_STAGE_SEPARATOR)
        if not separator or path != relative_path:
            continue
        fields = metadata.split()
        if len(fields) != 3:
            return None, MALFORMED_INDEX_ENTRY_REASON
        entries.append((fields[0], fields[1], fields[2]))
    return entries, EMPTY_ERROR


def _working_file_mode(path: Path, expected_mode: str, file_mode_enabled: bool) -> str:
    """Return the mode Git would stage for a working-tree path."""
    if path.is_symlink():
        return SYMLINK_FILE_MODE
    if not file_mode_enabled:
        return expected_mode
    file_mode = path.stat().st_mode
    return EXECUTABLE_FILE_MODE if file_mode & stat.S_IXUSR else DEFAULT_FILE_MODE


def residue_is_intact(project_root: Path, residue: FoldResidue) -> bool:
    """Check that working bytes, mode, and every index stage still identify this fold."""
    write = residue.write
    path = project_root / write.relative_path
    if write.rendered_content is None:
        if path.exists() or path.is_symlink():
            return False
    else:
        try:
            if path.read_bytes() != write.rendered_content.encode(UTF8_ENCODING):
                return False
            if _working_file_mode(path, residue.expected_mode, residue.file_mode_enabled) != residue.expected_mode:
                return False
        except OSError:
            return False

    entries, error = _index_entries(project_root, write.relative_path)
    if error or entries is None:
        return False
    head_index_entry = (
        [(residue.head_entry.mode, residue.head_entry.blob, INDEX_STAGE_ZERO)] if residue.head_entry is not None else []
    )
    allowed_entries = [head_index_entry]
    if residue.fold_blob is not None:
        allowed_entries.append([(residue.expected_mode, residue.fold_blob, INDEX_STAGE_ZERO)])
    if residue.formatted_blob is not None and residue.formatted_blob != residue.fold_blob:
        allowed_entries.append([(residue.expected_mode, residue.formatted_blob, INDEX_STAGE_ZERO)])
    if residue.fold_blob is None and not head_index_entry:
        allowed_entries.append([])
    return entries in allowed_entries

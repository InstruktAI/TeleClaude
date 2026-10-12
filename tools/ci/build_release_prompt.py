"""Prepare bounded, immutable evidence for a release inspector."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from difflib import unified_diff
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from git.objects.blob import Blob
from pydantic import BaseModel, ConfigDict

from teleclaude.git import GitCommandError, Repo
from tools.ci.export_manifests import export_manifests
from tools.ci.gha import append_output, repo_root
from tools.release.attempt import (
    AttemptIdentity,
    ReleaseDecisionMode,
    load_attempt_identity,
    validate_attempt_checkout,
)
from tools.release.evidence_contract import (
    BASELINE_DIRECTORY_NAME,
    DIFF_DIRECTORY_NAME,
    EVIDENCE_INDEX_FILENAME,
    EVIDENCE_SCHEMA_VERSION,
    PROMPT_FILENAME,
    PUBLIC_CONTRACTS_DIRECTORY_NAME,
    REPORT_SCHEMA_FILENAME,
    SOURCE_CONTRACT_DIRECTORY_NAME,
    SOURCE_DIRECTORY_NAME,
)
from tools.release.report_models import report_model

ATTEMPT_ARGUMENT = "--attempt"
OUTPUT_DIRECTORY_ARGUMENT = "--output-directory"
ATTEMPT_OUTPUT = "attempt_identity"
EVIDENCE_OUTPUT = "evidence_directory"
PROMPT_OUTPUT = "inspector_prompt"
DESCRIPTION = "Build bounded release-inspection evidence."
RELEASE_PROMPT = "docs/local/spec/release-inspector-prompt.md"
MANIFEST_DIRECTORY = "manifests"
MANIFEST_NAMES = ("cli-surface", "events", "config")
JSON_ENCODING = "utf-8"
JSON_ENSURE_ASCII = True
ENCODE_ERROR_MODE = "backslashreplace"
PRETTY_JSON_INDENT = 2
SEGMENT_CHARACTER_LIMIT = 12_000
INDEX_WIDTH = 6
SEGMENT_WIDTH = 4
STATUS_NAME_SEPARATOR = "\0"
GROUP_KEY_SEPARATOR = ":"
HYPHEN = "-"
DIFF_SUFFIX = ".diff"
SINGLE_LINE = "\n"
EMPTY = ""
NO_BASELINE = "A normal release inspection requires a completed publication baseline."
CHECKOUT_MISMATCH = "The repository checkout does not match the captured source revision."
CHECKOUT_DIRTY = "The source checkout must be clean before generating captured-source evidence."
UNSAFE_EVIDENCE_DIRECTORY = "The evidence output directory must be new and must not be a symlink."
EVIDENCE_INSIDE_SOURCE = "Evidence output must be outside the captured source checkout."
UNSAFE_REPOSITORY_PATH = "A Git tree contains a path that cannot be safely materialized."
GIT_METADATA_DIRECTORY = ".git"
SYMLINK_MODE = 0o120000
TREE_PATH_PREFIX = "./"
DIFF_ARGUMENTS = ("--no-ext-diff", "--no-renames", "--unified=40")
DIFF_FILE_HEADER = "diff --git "
DIFF_INVENTORY_MISMATCH = "The Git diff does not match the captured changed-path inventory."
HEAD_REFERENCE = "HEAD"
NAME_STATUS_ARGUMENTS = ("--name-status", "-z", "--no-renames")
PATH_SEPARATOR = "/"
MANIFEST_SUFFIX = ".md"
GIT_REFERENCE_SEPARATOR = ":"
JSON_MODE = "json"
CURRENT_DIRECTORY_MARKER = "."
PARENT_DIRECTORY_MARKER = ".."
BASELINE_PROMPT_PREFIX = "Baseline commit: "
SOURCE_PROMPT_PREFIX = "Captured source commit: "
READ_PROMPT_PREFIX = "Read "
MANIFEST_PROMPT_LINE = (
    f"Compare the separate files under {PUBLIC_CONTRACTS_DIRECTORY_NAME}/{BASELINE_DIRECTORY_NAME} and "
    f"{PUBLIC_CONTRACTS_DIRECTORY_NAME}/{SOURCE_CONTRACT_DIRECTORY_NAME} in bounded reads. "
    "The evidence index supplies their comparison metadata."
)
INDEX_PROMPT_SUFFIX = (
    " in bounded portions to account for changed areas and locate focused source/diff evidence. "
    "It retains the complete changed-path denominator and every indexed segment; those segments are not a reading checklist."
)
SOURCE_TREE_PROMPT_PREFIX = "The captured source tree is available under "
SOURCE_TREE_PROMPT_SUFFIX = " for consumer inspection."
SEGMENT_PROMPT = (
    "Read segments by their index entries; each segment is bounded and retains its source/baseline identities."
)
DELETED_TEXT_PROMPT = "Deleted text content is present in its indexed diff segments. Binary changes remain fully listed by path and status."
SCHEMA_PROMPT_PREFIX = "Return JSON matching "
SCHEMA_PROMPT_SUFFIX = (
    ". Set assessment_complete only when the version and breaking/upgrade assessment completed. "
    "Continue focused reads for accessible decision-relevant unknowns; selective summary coverage is not a completion gate. "
    "Required unresolved implications or actual evidence/execution limits require an incomplete report."
)
PUBLIC_CONTRACT_HEADING = "# Public contract comparison"
INDEX_HEADING = "# Evidence index"
SCHEMA_HEADING = "# Report schema"
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MANUAL_TASK_HEADING = "### Explicit-version summary task"
SEE_ALSO_HEADING = "## See Also"
MANUAL_TASK_PREFIX = (
    "You are preparing an optional evidence-grounded summary for an already selected release version.\n"
)
MANUAL_SCHEMA_SUFFIX = ". Return only release_notes and summary_complete. The evidence index includes bounded captured-history segments when no baseline exists."
HISTORY_FILENAME_TEMPLATE = "history-{number:06d}.txt"
HISTORY_LOG_FORMAT = "--format=%H %s"
SYMLINK_DATA_VALUE: Literal["symlink-data"] = "symlink-data"
FILE_VALUE: Literal["file"] = "file"


class ChangeStatus(StrEnum):
    """Git tree changes represented by the fixed source comparison."""

    ADDED = "A"
    DELETED = "D"
    MODIFIED = "M"
    TYPE_CHANGED = "T"


class EvidenceRecord(BaseModel):
    """Strict JSON record shared by the evidence index structures."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ChangedFile(EvidenceRecord):
    """One path in the complete baseline-to-source change denominator."""

    status: ChangeStatus
    path: str


class ResourceGroup(EvidenceRecord):
    """Paths grouped by directory and Git change status."""

    group: str
    status: ChangeStatus
    paths: list[str]


class DiffSegmentEntry(EvidenceRecord):
    """Bounded diff segments for one changed path."""

    status: ChangeStatus
    path: str
    source_sha: str
    baseline_sha: str | None
    segments: list[str]


class SourceFileEntry(EvidenceRecord):
    """A source-tree file and the representation used for its Git mode."""

    path: str
    mode: int
    representation: Literal["file", "symlink-data"]


class ContractComparison(EvidenceRecord):
    """Generated source contract compared with its published counterpart."""

    name: str
    baseline_available: bool
    source_path: str
    baseline_path: str | None
    diff: str


class PublicContractsEvidence(EvidenceRecord):
    """Source and baseline identity for all public contract manifests."""

    source_sha: str
    baseline_sha: str | None
    manifests: list[ContractComparison]


class EvidenceIndex(EvidenceRecord):
    """Complete machine-readable denominator and evidence navigation map."""

    schema_version: int
    source_sha: str
    baseline_sha: str | None
    baseline_tag: str | None
    changed_files: list[ChangedFile]
    resource_groups: list[ResourceGroup]
    diff_segments: list[DiffSegmentEntry]
    source_files: list[SourceFileEntry]
    excluded_git_metadata_paths: list[str]
    public_contracts: PublicContractsEvidence
    report_schema: str
    history_segments: list[str]


def build_evidence(repo: Repo, attempt: AttemptIdentity, output_directory: Path) -> Path:
    """Materialize the complete source view, changed-file inventory, and bounded prompt."""
    if attempt.decision_mode is ReleaseDecisionMode.AUTOMATIC and (
        attempt.baseline_sha is None or attempt.baseline_tag is None
    ):
        raise ValueError(NO_BASELINE)
    validate_attempt_checkout(repo, attempt)
    if repo.commit(HEAD_REFERENCE).hexsha != attempt.source_sha:
        raise ValueError(CHECKOUT_MISMATCH)
    if repo.is_dirty(untracked_files=True):
        raise ValueError(CHECKOUT_DIRTY)
    repository_root = Path(repo.working_tree_dir or repo.working_dir).resolve()
    if output_directory.resolve().is_relative_to(repository_root):
        raise ValueError(EVIDENCE_INSIDE_SOURCE)
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(UNSAFE_EVIDENCE_DIRECTORY)
    output_directory.mkdir(parents=True)

    source_root = output_directory / SOURCE_DIRECTORY_NAME
    source_root.mkdir()
    source_entries, excluded_paths = _materialize_source(repo, attempt.source_sha, source_root)
    changes = _changed_files(repo, attempt)
    grouped_resources = _group_changes(changes)
    segment_index = _write_diffs(repo, attempt, changes, output_directory)
    contract_index = _write_public_contracts(repo, attempt, output_directory)
    schema_path = output_directory / REPORT_SCHEMA_FILENAME
    _write_json(schema_path, report_model(attempt.decision_mode).model_json_schema())

    index = EvidenceIndex(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        source_sha=attempt.source_sha,
        baseline_sha=attempt.baseline_sha,
        baseline_tag=attempt.baseline_tag,
        changed_files=changes,
        resource_groups=grouped_resources,
        diff_segments=segment_index,
        source_files=source_entries,
        excluded_git_metadata_paths=excluded_paths,
        public_contracts=contract_index,
        report_schema=REPORT_SCHEMA_FILENAME,
        history_segments=_write_history(repo, attempt, output_directory),
    )
    index_path = output_directory / EVIDENCE_INDEX_FILENAME
    _write_json(index_path, index.model_dump(mode=JSON_MODE))
    prompt_path = output_directory / PROMPT_FILENAME
    prompt_path.write_text(
        _make_prompt(repo, attempt, index_path, schema_path, output_directory),
        encoding=JSON_ENCODING,
    )
    return prompt_path


def _write_history(repo: Repo, attempt: AttemptIdentity, output: Path) -> list[str]:
    """Retain reachable commit navigation for a first manually versioned release."""
    if attempt.baseline_sha is not None:
        return []
    history = str(repo.git.log(HISTORY_LOG_FORMAT, attempt.source_sha))
    paths: list[str] = []
    for offset in range(0, len(history), SEGMENT_CHARACTER_LIMIT):
        name = HISTORY_FILENAME_TEMPLATE.format(number=len(paths) + 1)
        _write_text(output / name, history[offset : offset + SEGMENT_CHARACTER_LIMIT])
        paths.append(name)
    return paths


def _changed_files(repo: Repo, attempt: AttemptIdentity) -> list[ChangedFile]:
    """Read the full changed-path denominator from the captured Git objects."""
    raw = str(repo.git.diff(*NAME_STATUS_ARGUMENTS, attempt.baseline_sha or EMPTY_TREE_SHA, attempt.source_sha))
    fields = raw.split(STATUS_NAME_SEPARATOR)
    changes: list[ChangedFile] = []
    for position in range(0, len(fields) - 1, 2):
        status = ChangeStatus(fields[position])
        path = _safe_repository_path(fields[position + 1])
        changes.append(ChangedFile(status=status, path=path))
    return changes


def _group_changes(changes: list[ChangedFile]) -> list[ResourceGroup]:
    """Group repeated resources by their directory and Git change status."""
    groups: dict[tuple[ChangeStatus, str], list[str]] = defaultdict(list)
    for entry in changes:
        directory = PurePosixPath(entry.path).parent.as_posix()
        groups[(entry.status, directory)].append(entry.path)
    return [
        ResourceGroup(
            group=GROUP_KEY_SEPARATOR.join((status.value, directory)),
            status=status,
            paths=paths,
        )
        for (status, directory), paths in sorted(groups.items())
    ]


def _write_diffs(
    repo: Repo,
    attempt: AttemptIdentity,
    changes: list[ChangedFile],
    output_directory: Path,
) -> list[DiffSegmentEntry]:
    """Write a complete diff once and index its bounded, grouped segments by path."""
    raw_diff = str(repo.git.diff(*DIFF_ARGUMENTS, attempt.baseline_sha or EMPTY_TREE_SHA, attempt.source_sha))
    diff_sections = _split_diff_sections(raw_diff)
    if len(diff_sections) != len(changes):
        raise ValueError(DIFF_INVENTORY_MISMATCH)
    segments_root = output_directory / DIFF_DIRECTORY_NAME
    segments_root.mkdir()
    grouped_sections: dict[tuple[ChangeStatus, str], list[tuple[ChangedFile, str]]] = defaultdict(list)
    for entry, section in zip(changes, diff_sections, strict=True):
        directory = PurePosixPath(entry.path).parent.as_posix()
        grouped_sections[(entry.status, directory)].append((entry, section))
    path_segments: dict[str, list[str]] = {}
    for group_index, group_key in enumerate(sorted(grouped_sections), start=1):
        path_segments.update(_write_group_diffs(group_index, grouped_sections[group_key], segments_root))
    return [
        DiffSegmentEntry(
            status=entry.status,
            path=entry.path,
            source_sha=attempt.source_sha,
            baseline_sha=attempt.baseline_sha,
            segments=path_segments[entry.path],
        )
        for entry in changes
    ]


def _split_diff_sections(raw_diff: str) -> list[str]:
    """Split Git's unified diff only at file headers that begin a line."""
    sections: list[str] = []
    current: list[str] = []
    for line in raw_diff.splitlines(keepends=True):
        if line.startswith(DIFF_FILE_HEADER):
            if current:
                sections.append(EMPTY.join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append(EMPTY.join(current))
    return sections


def _write_group_diffs(
    group_index: int,
    sections: list[tuple[ChangedFile, str]],
    destination: Path,
) -> dict[str, list[str]]:
    """Pack small file diffs by resource group and split large diffs safely."""
    path_segments: dict[str, list[str]] = defaultdict(list)
    pending = EMPTY
    pending_paths: list[str] = []
    segment_number = 0

    def flush_pending() -> None:
        nonlocal pending, pending_paths, segment_number
        if not pending:
            return
        segment_number += 1
        segment_path = _segment_relative_path(group_index, segment_number)
        _write_text(
            destination / segment_path.removeprefix(DIFF_DIRECTORY_NAME + PATH_SEPARATOR),
            _escape_unencodable_text(pending),
        )
        for changed_path in pending_paths:
            path_segments[changed_path].append(segment_path)
        pending = EMPTY
        pending_paths = []

    for entry, section in sections:
        if len(section) > SEGMENT_CHARACTER_LIMIT:
            flush_pending()
            for start in range(0, len(section), SEGMENT_CHARACTER_LIMIT):
                segment_number += 1
                segment_path = _segment_relative_path(group_index, segment_number)
                segment_file = destination / segment_path.removeprefix(DIFF_DIRECTORY_NAME + PATH_SEPARATOR)
                _write_text(segment_file, _escape_unencodable_text(section[start : start + SEGMENT_CHARACTER_LIMIT]))
                path_segments[entry.path].append(segment_path)
            continue
        if pending and len(pending) + len(section) > SEGMENT_CHARACTER_LIMIT:
            flush_pending()
        pending += section
        pending_paths.append(entry.path)
    flush_pending()
    return path_segments


def _materialize_source(
    repo: Repo,
    source_sha: str,
    destination: Path,
) -> tuple[list[SourceFileEntry], list[str]]:
    """Write captured source blobs as regular files, preserving symlinks as data."""
    source_entries: list[SourceFileEntry] = []
    excluded_paths: list[str] = []
    for item in repo.commit(source_sha).tree.traverse():
        if not isinstance(item, Blob):
            continue
        path = str(item.path).removeprefix(TREE_PATH_PREFIX)
        safe_path = _safe_repository_path(path)
        if GIT_METADATA_DIRECTORY in PurePosixPath(safe_path).parts:
            excluded_paths.append(safe_path)
            continue
        source_path = destination.joinpath(*PurePosixPath(safe_path).parts)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(item.data_stream.read())
        source_entries.append(
            SourceFileEntry(
                path=safe_path,
                mode=item.mode,
                representation=SYMLINK_DATA_VALUE if item.mode == SYMLINK_MODE else FILE_VALUE,
            )
        )
    return source_entries, excluded_paths


def _write_public_contracts(
    repo: Repo,
    attempt: AttemptIdentity,
    output_directory: Path,
) -> PublicContractsEvidence:
    """Generate source contracts without host configuration and compare the release baseline."""
    contract_root = output_directory / PUBLIC_CONTRACTS_DIRECTORY_NAME
    baseline_root = contract_root / BASELINE_DIRECTORY_NAME
    source_root = contract_root / SOURCE_CONTRACT_DIRECTORY_NAME
    baseline_root.mkdir(parents=True)
    source_root.mkdir(parents=True)
    export_manifests(source_root)
    comparisons: list[ContractComparison] = []
    for name in MANIFEST_NAMES:
        manifest_name = name + MANIFEST_SUFFIX
        manifest_path = MANIFEST_DIRECTORY + PATH_SEPARATOR + manifest_name
        baseline_text: str | None
        try:
            baseline_text = (
                str(repo.git.show(attempt.baseline_sha + GIT_REFERENCE_SEPARATOR + manifest_path))
                if attempt.baseline_sha is not None
                else None
            )
        except GitCommandError:
            baseline_text = None
        source_text = (source_root / manifest_name).read_text(encoding=JSON_ENCODING)
        if baseline_text is not None:
            _write_text(baseline_root / manifest_name, baseline_text)
        diff = (
            EMPTY
            if baseline_text is None
            else EMPTY.join(
                unified_diff(
                    baseline_text.splitlines(keepends=True),
                    source_text.splitlines(keepends=True),
                    fromfile=BASELINE_DIRECTORY_NAME + PATH_SEPARATOR + manifest_name,
                    tofile=SOURCE_CONTRACT_DIRECTORY_NAME + PATH_SEPARATOR + manifest_name,
                )
            )
        )
        comparisons.append(
            ContractComparison(
                name=manifest_name,
                baseline_available=baseline_text is not None,
                source_path=PUBLIC_CONTRACTS_DIRECTORY_NAME
                + PATH_SEPARATOR
                + SOURCE_CONTRACT_DIRECTORY_NAME
                + PATH_SEPARATOR
                + manifest_name,
                baseline_path=(
                    PUBLIC_CONTRACTS_DIRECTORY_NAME
                    + PATH_SEPARATOR
                    + BASELINE_DIRECTORY_NAME
                    + PATH_SEPARATOR
                    + manifest_name
                    if baseline_text is not None
                    else None
                ),
                diff=diff,
            )
        )
    return PublicContractsEvidence(
        source_sha=attempt.source_sha,
        baseline_sha=attempt.baseline_sha,
        manifests=comparisons,
    )


def _make_prompt(
    repo: Repo,
    attempt: AttemptIdentity,
    index_path: Path,
    schema_path: Path,
    output_directory: Path,
) -> str:
    """Combine the canonical inspector contract with only bounded navigation facts."""
    root = Path(repo.working_tree_dir or repo.working_dir)
    contract = (root / RELEASE_PROMPT).read_text(encoding=JSON_ENCODING)
    if attempt.decision_mode is ReleaseDecisionMode.MANUAL:
        contract = contract.split(MANUAL_TASK_HEADING, 1)[1].split(SEE_ALSO_HEADING, 1)[0]
        contract = MANUAL_TASK_PREFIX + contract
    index_relative = index_path.relative_to(output_directory)
    schema_relative = schema_path.relative_to(output_directory)
    source_relative = Path(SOURCE_DIRECTORY_NAME)
    return SINGLE_LINE.join(
        (
            contract,
            EMPTY,
            PUBLIC_CONTRACT_HEADING,
            BASELINE_PROMPT_PREFIX + str(attempt.baseline_sha),
            SOURCE_PROMPT_PREFIX + attempt.source_sha,
            MANIFEST_PROMPT_LINE,
            EMPTY,
            INDEX_HEADING,
            READ_PROMPT_PREFIX + str(index_relative) + INDEX_PROMPT_SUFFIX,
            SOURCE_TREE_PROMPT_PREFIX + str(source_relative) + SOURCE_TREE_PROMPT_SUFFIX,
            SEGMENT_PROMPT,
            DELETED_TEXT_PROMPT,
            EMPTY,
            SCHEMA_HEADING,
            SCHEMA_PROMPT_PREFIX
            + str(schema_relative)
            + (MANUAL_SCHEMA_SUFFIX if attempt.decision_mode is ReleaseDecisionMode.MANUAL else SCHEMA_PROMPT_SUFFIX),
        )
    )


def _segment_relative_path(group_index: int, segment_number: int) -> str:
    """Return a stable path for one grouped diff segment."""
    name = str(group_index).zfill(INDEX_WIDTH) + HYPHEN + str(segment_number).zfill(SEGMENT_WIDTH) + DIFF_SUFFIX
    return DIFF_DIRECTORY_NAME + PATH_SEPARATOR + name


def _safe_repository_path(path: str) -> str:
    """Reject absolute or traversing paths before writing evidence files."""
    pure_path = PurePosixPath(path)
    if (
        not path
        or pure_path.is_absolute()
        or any(part in {EMPTY, CURRENT_DIRECTORY_MARKER, PARENT_DIRECTORY_MARKER} for part in pure_path.parts)
    ):
        raise ValueError(UNSAFE_REPOSITORY_PATH)
    return pure_path.as_posix()


def _write_json(path: Path, value: object) -> None:
    """Write deterministic JSON evidence."""
    path.write_text(
        json.dumps(value, ensure_ascii=JSON_ENSURE_ASCII, indent=PRETTY_JSON_INDENT, sort_keys=True) + SINGLE_LINE,
        encoding=JSON_ENCODING,
    )


def _write_text(path: Path, value: str) -> None:
    """Write one text evidence item with its exact supplied contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding=JSON_ENCODING)


def _escape_unencodable_text(value: str) -> str:
    """Keep non-UTF-8 Git path/content bytes readable as explicit escapes."""
    return value.encode(JSON_ENCODING, errors=ENCODE_ERROR_MODE).decode(JSON_ENCODING)


def main(argv: list[str] | None = None) -> int:
    """Build evidence from a captured attempt for downstream inspector jobs."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(ATTEMPT_ARGUMENT, type=Path, required=True)
    parser.add_argument(OUTPUT_DIRECTORY_ARGUMENT, type=Path, required=True)
    arguments = parser.parse_args(argv)
    attempt = load_attempt_identity(arguments.attempt)
    repo = Repo(repo_root())
    prompt_path = build_evidence(repo, attempt, arguments.output_directory)
    append_output(ATTEMPT_OUTPUT, str(arguments.attempt))
    append_output(EVIDENCE_OUTPUT, str(arguments.output_directory))
    append_output(PROMPT_OUTPUT, str(prompt_path))
    print(str(prompt_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

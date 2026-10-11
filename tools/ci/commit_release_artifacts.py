"""Freeze one release decision and verified commit notes into a versioned candidate bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from git import Actor
from pydantic import ValidationError

from teleclaude.git import Repo
from tools.ci.compute_next_version import ReleaseBump, next_tag
from tools.ci.export_manifests import export_manifests
from tools.ci.gha import append_output, repo_root
from tools.ci.read_inspector_report import InspectorSelection
from tools.release.attempt import (
    AttemptIdentity,
    CandidateIdentity,
    ReleaseDecisionMode,
    load_attempt_identity,
    release_decision_digest,
    validate_attempt_checkout,
)
from tools.release.changelog import (
    MAX_RELEASE_BODY_BYTES,
    assemble_section,
    prepend_to_changelog,
    verify_commit_notes,
)
from tools.release.project_metadata import (
    normalize_release_owned_file,
    normalized_tree_digest,
    read_locked_project_version,
    read_project_version,
)

_AUTHOR_EMAIL = "github-actions[bot]@users.noreply.github.com"
_AUTHOR_NAME = "github-actions[bot]"
_CHANGELOG = "CHANGELOG.md"
_BUNDLE_FILENAME = "candidate.bundle"
_CANDIDATE_FILENAME = "candidate-identity.json"
_COMMIT_NOTES_FILENAME = "commit-notes.md"
_PROVENANCE_FILENAME = "release-provenance.json"
_COMMIT_PREFIX = "chore: bump version to "
_COMMIT_SUFFIX = " [skip ci]"
_DESCRIPTION = "Create a version-coherent release candidate and incremental bundle."
_MANIFESTS = ("manifests/cli-surface.md", "manifests/events.md", "manifests/config.md")
_MANIFEST_DIRECTORY = "manifests"
_PYPROJECT = "pyproject.toml"
_LOCK = "uv.lock"
_GIT = "git"
_UV = "uv"
_GIT_STATUS = "status"
_GIT_STATUS_PORCELAIN = "--porcelain"
_GIT_SHOW = "show"
_GIT_DIFF = "diff"
_GIT_NAME_ONLY = "--name-only"
_GIT_NULL_DELIMITER = "-z"
_GIT_BUNDLE = "bundle"
_GIT_BUNDLE_CREATE = "create"
_GIT_BUNDLE_VERIFY = "verify"
_GIT_HEAD_REFERENCE = "HEAD"
_GIT_EXCLUSION_PREFIX = "^"
_UV_VERSION = "version"
_UV_NO_SYNC = "--no-sync"
_STRICT_DECODING = "strict"
_VERSION_PREFIX = "v"
_JSON_MODE = "json"
_GITHUB_OUTPUT_VARIABLE = "GITHUB_OUTPUT"
_CANDIDATE_SHA_OUTPUT = "candidate_sha"
_CANDIDATE_TREE_SHA_OUTPUT = "candidate_tree_sha"
_CANDIDATE_VERSION_OUTPUT = "candidate_version"
_CANDIDATE_BUNDLE_DIGEST_OUTPUT = "candidate_bundle_sha256"
_CANDIDATE_SUMMARY_TEMPLATE = "Candidate {} ({}); bundle sha256 {}"
_BASELINE_CHANGELOG_REFERENCE_TEMPLATE = "{}:{}"
_NUL = "\0"
_UTF8 = "utf-8"
_JSON_INDENT = 2
_NEWLINE = "\n"
_EMPTY = ""
_SCHEMA_VERSION_KEY = "schema_version"
_ATTEMPT_KEY = "attempt"
_DECISION_MODE_KEY = "decision_mode"
_REQUESTED_VERSION_KEY = "requested_version"
_VERSION_KEY = "version"
_DECISION_DIGEST_KEY = "decision_sha256"
_SELECTED_PROVIDER_KEY = "selected_provider"
_ASSESSMENT_DIGEST_KEY = "assessment_sha256"
_LEGACY_ASSESSMENT_DIGEST_KEY = "legacy_assessment_sha256"
_COMMIT_NOTES_DIGEST_KEY = "commit_notes_sha256"
_CODEX_ATTEMPT_KEY = "codex_attempt"
_CLAUDE_ATTEMPT_KEY = "claude_attempt"
_STATUS_CLEAN = ""
_NO_BASELINE = "A normal release candidate requires its captured publication baseline."
_MANUAL_DECISION_VERSION_MISMATCH = "The requested candidate version does not match its captured manual decision."
_COMMIT_NOTES_REQUIRED = "The verified shared generated commit notes are required before preparing a candidate."
_RELEASE_SECTION_TOO_LARGE = "The complete generated release section exceeds the supported release-body size."
_WORKTREE_DIRTY = "Candidate preparation requires the captured source checkout to be clean."
_REPORT_INVALID = "The selected inspection record is incomplete or inconsistent."
_VERSION_MISMATCH = "The requested candidate version does not match the selected classification."
_LOCK_CHANGED = "The version update changed uv.lock dependency resolutions."
_METADATA_INCOHERENT = "The project and editable lock package versions do not match the candidate."
_UNEXPECTED_CANDIDATE_PATH = "Candidate preparation changed a path outside release-owned metadata."
_CANDIDATE_TREE_MISMATCH = "The candidate changed source content outside release-owned metadata."
_CANDIDATE_PARENT_MISMATCH = "The candidate is not an ordinary child of captured source."
_OUTPUT_DIRECTORY_INVALID = "Candidate artifacts require a new directory outside the checkout."
_COMMAND_FAILED = "Candidate-preparation command {command} failed with exit code {return_code}."


def prepare_candidate(
    repository_root: Path,
    attempt: AttemptIdentity,
    selection: InspectorSelection | None,
    version_tag: str,
    output_directory: Path,
    commit_notes_file: Path,
) -> CandidateIdentity:
    """Create candidate R as one child of captured S and bind its transfer bundle."""
    root = repository_root.resolve()
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(_OUTPUT_DIRECTORY_INVALID)
    output = output_directory.resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError(_OUTPUT_DIRECTORY_INVALID)
    repo = Repo(root)
    validate_attempt_checkout(repo, attempt)
    if _git(root, _GIT_STATUS, _GIT_STATUS_PORCELAIN) != _STATUS_CLEAN:
        raise ValueError(_WORKTREE_DIRTY)
    selected_provider, report_bytes, assessment_digest = _assessment_metadata(
        attempt,
        selection,
        version_tag,
    )
    if attempt.decision_mode == ReleaseDecisionMode.AUTOMATIC and report_bytes is None:
        raise ValueError(_REPORT_INVALID)
    if attempt.decision_mode == ReleaseDecisionMode.MANUAL and report_bytes is not None:
        raise ValueError(_REPORT_INVALID)
    if not commit_notes_file.is_file():
        raise ValueError(_COMMIT_NOTES_REQUIRED)
    commit_notes = commit_notes_file.read_bytes()
    commit_notes_text = commit_notes.decode(_UTF8, errors=_STRICT_DECODING)
    verify_commit_notes(root, attempt.source_sha, attempt.baseline_sha, commit_notes_file)
    commit_notes_digest = hashlib.sha256(commit_notes).hexdigest()
    version = version_tag.removeprefix(_VERSION_PREFIX)
    output.mkdir(mode=0o700, parents=True)
    (output / _COMMIT_NOTES_FILENAME).write_bytes(commit_notes)

    previous_project_version = read_project_version(root)
    previous_lock_version = read_locked_project_version(root)
    lock_before = (root / _LOCK).read_bytes()
    _run(root, [_UV, _UV_VERSION, _UV_NO_SYNC, version])
    if read_project_version(root) != version or read_locked_project_version(root) != version:
        raise ValueError(_METADATA_INCOHERENT)
    lock_after = (root / _LOCK).read_bytes()
    if normalize_release_owned_file(_LOCK, lock_before) != normalize_release_owned_file(_LOCK, lock_after):
        raise ValueError(_LOCK_CHANGED)
    if previous_project_version != previous_lock_version:
        raise ValueError(_METADATA_INCOHERENT)

    export_manifests(root / _MANIFEST_DIRECTORY)
    previous_tag = attempt.baseline_tag
    if previous_tag is not None:
        changelog_before = _git_bytes(
            root,
            _GIT_SHOW,
            _BASELINE_CHANGELOG_REFERENCE_TEMPLATE.format(previous_tag, _CHANGELOG),
        )
        (root / _CHANGELOG).write_bytes(changelog_before)
    summary = selection.selected_report.release_notes if selection is not None else None
    section = assemble_section(
        version,
        datetime.now(UTC).date().isoformat(),
        commit_notes_text,
        summary,
        attempt.baseline_tag,
    )
    if len(section.encode(_UTF8)) > MAX_RELEASE_BODY_BYTES:
        raise ValueError(_RELEASE_SECTION_TOO_LARGE)
    prepend_to_changelog(section, root / _CHANGELOG)
    provenance = {
        _SCHEMA_VERSION_KEY: 2,
        _ATTEMPT_KEY: attempt.model_dump(mode=_JSON_MODE),
        _DECISION_MODE_KEY: attempt.decision_mode.value,
        _REQUESTED_VERSION_KEY: attempt.requested_version,
        _VERSION_KEY: version_tag,
        _DECISION_DIGEST_KEY: release_decision_digest(
            attempt,
            version_tag,
            assessment_digest,
            None,
        ),
        _COMMIT_NOTES_DIGEST_KEY: commit_notes_digest,
        _SELECTED_PROVIDER_KEY: selected_provider,
        _ASSESSMENT_DIGEST_KEY: assessment_digest,
        _LEGACY_ASSESSMENT_DIGEST_KEY: None,
        _CODEX_ATTEMPT_KEY: (selection.codex_attempt.model_dump(mode=_JSON_MODE) if selection is not None else None),
        _CLAUDE_ATTEMPT_KEY: (
            selection.claude_attempt.model_dump(mode=_JSON_MODE)
            if selection is not None and selection.claude_attempt is not None
            else None
        ),
    }
    (root / _PROVENANCE_FILENAME).write_text(
        json.dumps(provenance, ensure_ascii=True, indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )

    candidate_paths = (_PYPROJECT, _LOCK, *_MANIFESTS, _CHANGELOG, _PROVENANCE_FILENAME)
    changed = set(_git(root, _GIT_DIFF, _GIT_NAME_ONLY, _GIT_NULL_DELIMITER, attempt.source_sha).split(_NUL)) - {_EMPTY}
    if not changed or not changed.issubset(candidate_paths):
        raise ValueError(_UNEXPECTED_CANDIDATE_PATH)
    repo.index.add(list(candidate_paths))
    actor = Actor(_AUTHOR_NAME, _AUTHOR_EMAIL)
    commit = repo.index.commit(_COMMIT_PREFIX + version + _COMMIT_SUFFIX, author=actor, committer=actor)
    candidate_sha = commit.hexsha
    if len(commit.parents) != 1 or commit.parents[0].hexsha != attempt.source_sha:
        raise ValueError(_CANDIDATE_PARENT_MISMATCH)
    if normalized_tree_digest(repo, attempt.source_sha) != normalized_tree_digest(repo, candidate_sha):
        raise ValueError(_CANDIDATE_TREE_MISMATCH)
    candidate_changed = set(
        _git(root, _GIT_DIFF, _GIT_NAME_ONLY, _GIT_NULL_DELIMITER, attempt.source_sha, candidate_sha).split(_NUL)
    ) - {_EMPTY}
    if not candidate_changed or not candidate_changed.issubset(candidate_paths):
        raise ValueError(_UNEXPECTED_CANDIDATE_PATH)

    bundle_path = output / _BUNDLE_FILENAME
    _run(
        root,
        [
            _GIT,
            _GIT_BUNDLE,
            _GIT_BUNDLE_CREATE,
            str(bundle_path),
            _GIT_HEAD_REFERENCE,
            _GIT_EXCLUSION_PREFIX + attempt.source_sha,
        ],
    )
    _run(root, [_GIT, _GIT_BUNDLE, _GIT_BUNDLE_VERIFY, str(bundle_path)])
    bundle_digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    identity = CandidateIdentity(
        attempt=attempt,
        version=version_tag,
        candidate_sha=candidate_sha,
        candidate_tree_sha=commit.tree.hexsha,
        assessment_sha256=assessment_digest,
        decision_sha256=release_decision_digest(
            attempt,
            version_tag,
            assessment_digest,
            None,
        ),
        commit_notes_sha256=commit_notes_digest,
        legacy_assessment_sha256=None,
        bundle_sha256=bundle_digest,
    )
    (output / _CANDIDATE_FILENAME).write_text(
        identity.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    if os.environ.get(_GITHUB_OUTPUT_VARIABLE):
        append_output(_CANDIDATE_SHA_OUTPUT, identity.candidate_sha)
        append_output(_CANDIDATE_TREE_SHA_OUTPUT, identity.candidate_tree_sha)
        append_output(_CANDIDATE_VERSION_OUTPUT, identity.version)
        append_output(_CANDIDATE_BUNDLE_DIGEST_OUTPUT, bundle_digest)
    print(_CANDIDATE_SUMMARY_TEMPLATE.format(candidate_sha, version_tag, bundle_digest))
    return identity


def _assessment_metadata(
    attempt: AttemptIdentity,
    selection: InspectorSelection | None,
    version_tag: str,
) -> tuple[str | None, bytes | None, str | None]:
    """Validate an automatic assessment or the version recorded in a manual decision."""
    if attempt.decision_mode == ReleaseDecisionMode.MANUAL:
        if selection is not None:
            raise ValueError(_REPORT_INVALID)
        if attempt.requested_version is None or version_tag != attempt.requested_version:
            raise ValueError(_MANUAL_DECISION_VERSION_MISMATCH)
        return None, None, None
    if attempt.baseline_tag is None or attempt.baseline_sha is None or selection is None:
        raise ValueError(_NO_BASELINE)
    report = selection.selected_report
    selected_attempt = selection.codex_attempt if selection.selected_provider == "codex" else selection.claude_attempt
    if (
        not report.assessment_complete
        or selected_attempt is None
        or selected_attempt.outcome.value != "succeeded"
        or selected_attempt.failure is not None
    ):
        raise ValueError(_REPORT_INVALID)
    if selection.selected_provider == "codex" and not selected_attempt.auth_settled:
        raise ValueError(_REPORT_INVALID)
    report_bytes = report.model_dump_json().encode(_UTF8)
    assessment_digest = hashlib.sha256(report_bytes).hexdigest()
    if selected_attempt.report_sha256 != assessment_digest:
        raise ValueError(_REPORT_INVALID)
    if report.classification not in {ReleaseBump.PATCH.value, ReleaseBump.MINOR.value}:
        raise ValueError(_REPORT_INVALID)
    if version_tag != next_tag(attempt.baseline_tag, ReleaseBump(report.classification)):
        raise ValueError(_VERSION_MISMATCH)
    return selection.selected_provider, report_bytes, assessment_digest


def _run(root: Path, arguments: Sequence[str]) -> str:
    """Run one fixed command without shell interpretation or secret output."""
    try:
        result = subprocess.run(arguments, cwd=root, capture_output=True, check=True, text=True)
    except subprocess.CalledProcessError as error:
        command = Path(arguments[0]).name
        if len(arguments) > 2 and arguments[1] == "-m":
            command += " -m " + arguments[2]
        raise RuntimeError(_COMMAND_FAILED.format(command=command, return_code=error.returncode)) from None
    except OSError:
        raise RuntimeError(_COMMAND_FAILED.format(command=Path(arguments[0]).name, return_code="unavailable")) from None
    return result.stdout.strip()


def _git(root: Path, *arguments: str) -> str:
    """Run a read-only Git query in the candidate checkout."""
    return _run(root, [_GIT, *arguments])


def _git_bytes(root: Path, *arguments: str) -> bytes:
    """Read exact baseline file bytes without using the moving working-tree copy."""
    try:
        result = subprocess.run([_GIT, *arguments], cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError(_COMMAND_FAILED) from None
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    """Load immutable inputs and write a candidate identity plus incremental bundle."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--version", required=True, help="Selected next semantic tag, such as v1.2.3.")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--commit-notes-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        attempt = load_attempt_identity(args.attempt)
        selection = InspectorSelection.model_validate_json(args.selection.read_bytes()) if args.selection else None
        prepare_candidate(
            repo_root(),
            attempt,
            selection,
            args.version,
            args.output_directory,
            args.commit_notes_file,
        )
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

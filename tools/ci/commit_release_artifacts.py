"""Freeze one selected assessment into a versioned candidate and incremental bundle."""

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
    load_attempt_identity,
    validate_attempt_checkout,
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
_PROVENANCE_FILENAME = "release-provenance.json"
_BOOTSTRAP_VERSION = "v0.7.0"
_COMMIT_PREFIX = "chore: bump version to "
_COMMIT_SUFFIX = " [skip ci]"
_DESCRIPTION = "Create a version-coherent release candidate and incremental bundle."
_MANIFESTS = ("manifests/cli-surface.md", "manifests/events.md", "manifests/config.md")
_PYPROJECT = "pyproject.toml"
_LOCK = "uv.lock"
_GIT = "git"
_UV = "uv"
_UTF8 = "utf-8"
_JSON_INDENT = 2
_NEWLINE = "\n"
_EMPTY = ""
_STATUS_CLEAN = ""
_NO_BASELINE = "A normal release candidate requires its captured publication baseline."
_BOOTSTRAP_UNSUPPORTED = "Bootstrap candidate preparation uses the explicit Task 7 route."
_BOOTSTRAP_VERSION_MISMATCH = "The initial current-state baseline version is fixed at v0.7.0."
_BOOTSTRAP_NOTES_REQUIRED = "Bootstrap candidate preparation requires authorized current-state notes."
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
    *,
    bootstrap_notes: str | None = None,
    bootstrap_previous_tag: str | None = None,
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
    if _git(root, "status", "--porcelain") != _STATUS_CLEAN:
        raise ValueError(_WORKTREE_DIRTY)
    selected_provider, report_bytes, assessment_digest = _assessment_metadata(
        attempt,
        selection,
        version_tag,
        bootstrap_notes,
    )
    version = version_tag.removeprefix("v")
    output.mkdir(mode=0o700, parents=True)
    selected_report_path = output / "selected-report.json"
    if selection is not None:
        selected_report_path.write_bytes(report_bytes)
    else:
        selected_report_path = output / "bootstrap-notes.md"
        selected_report_path.write_text((bootstrap_notes or _EMPTY).strip() + _NEWLINE, encoding=_UTF8)

    previous_project_version = read_project_version(root)
    previous_lock_version = read_locked_project_version(root)
    lock_before = (root / _LOCK).read_bytes()
    _run(root, [_UV, "version", "--no-sync", version])
    if read_project_version(root) != version or read_locked_project_version(root) != version:
        raise ValueError(_METADATA_INCOHERENT)
    lock_after = (root / _LOCK).read_bytes()
    if normalize_release_owned_file(_LOCK, lock_before) != normalize_release_owned_file(_LOCK, lock_after):
        raise ValueError(_LOCK_CHANGED)
    if previous_project_version != previous_lock_version:
        raise ValueError(_METADATA_INCOHERENT)

    export_manifests(root / "manifests")
    previous_tag = attempt.baseline_tag if not attempt.bootstrap else bootstrap_previous_tag
    if previous_tag is not None:
        changelog_before = _git_bytes(root, "show", f"{previous_tag}:{_CHANGELOG}")
        (root / _CHANGELOG).write_bytes(changelog_before)
    if attempt.bootstrap:
        changelog_arguments = [
            sys.executable,
            "-m",
            "tools.release.changelog",
            "from-bootstrap",
            "--tag",
            version_tag,
            "--notes-file",
            str(selected_report_path),
            "--date",
            datetime.now(UTC).date().isoformat(),
            "--prepend",
            _CHANGELOG,
        ]
        if previous_tag is not None:
            changelog_arguments.extend(("--since", previous_tag))
    else:
        changelog_arguments = [
            sys.executable,
            "-m",
            "tools.release.changelog",
            "from-report",
            "--tag",
            version_tag,
            "--since",
            attempt.baseline_tag or _EMPTY,
            "--until",
            attempt.source_sha,
            "--date",
            datetime.now(UTC).date().isoformat(),
            "--report",
            str(selected_report_path),
            "--prepend",
            _CHANGELOG,
        ]
    _run(root, changelog_arguments)
    provenance = {
        "schema_version": 1,
        "attempt": attempt.model_dump(mode="json"),
        "selected_provider": selected_provider,
        "assessment_sha256": assessment_digest,
        "codex_attempt": (selection.codex_attempt.model_dump(mode="json") if selection is not None else None),
        "claude_attempt": (
            selection.claude_attempt.model_dump(mode="json")
            if selection is not None and selection.claude_attempt is not None
            else None
        ),
        "bootstrap_notes_sha256": assessment_digest if attempt.bootstrap else None,
    }
    (root / _PROVENANCE_FILENAME).write_text(
        json.dumps(provenance, ensure_ascii=True, indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )

    candidate_paths = (_PYPROJECT, _LOCK, *_MANIFESTS, _CHANGELOG, _PROVENANCE_FILENAME)
    changed = set(_git(root, "diff", "--name-only", "-z", attempt.source_sha).split("\0")) - {_EMPTY}
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
    candidate_changed = set(_git(root, "diff", "--name-only", "-z", attempt.source_sha, candidate_sha).split("\0")) - {
        _EMPTY
    }
    if not candidate_changed or not candidate_changed.issubset(candidate_paths):
        raise ValueError(_UNEXPECTED_CANDIDATE_PATH)

    bundle_path = output / _BUNDLE_FILENAME
    _run(root, [_GIT, "bundle", "create", str(bundle_path), "HEAD", "^" + attempt.source_sha])
    _run(root, [_GIT, "bundle", "verify", str(bundle_path)])
    bundle_digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    identity = CandidateIdentity(
        attempt=attempt,
        version=version_tag,
        candidate_sha=candidate_sha,
        candidate_tree_sha=commit.tree.hexsha,
        assessment_sha256=assessment_digest,
        bundle_sha256=bundle_digest,
    )
    (output / _CANDIDATE_FILENAME).write_text(
        identity.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    if os.environ.get("GITHUB_OUTPUT"):
        append_output("candidate_sha", identity.candidate_sha)
        append_output("candidate_tree_sha", identity.candidate_tree_sha)
        append_output("candidate_version", identity.version)
        append_output("candidate_bundle_sha256", bundle_digest)
    print(f"Candidate {candidate_sha} ({version_tag}); bundle sha256 {bundle_digest}")
    return identity


def _assessment_metadata(
    attempt: AttemptIdentity,
    selection: InspectorSelection | None,
    version_tag: str,
    bootstrap_notes: str | None,
) -> tuple[str, bytes, str]:
    """Validate one normal selected report or the explicitly authorized baseline notes."""
    if attempt.bootstrap:
        if selection is not None:
            raise ValueError(_BOOTSTRAP_UNSUPPORTED)
        if not bootstrap_notes or not bootstrap_notes.strip():
            raise ValueError(_BOOTSTRAP_NOTES_REQUIRED)
        if version_tag != _BOOTSTRAP_VERSION:
            raise ValueError(_BOOTSTRAP_VERSION_MISMATCH)
        report_bytes = json.dumps(
            {"bootstrap_notes": bootstrap_notes.strip(), "version": version_tag},
            ensure_ascii=True,
            sort_keys=True,
        ).encode(_UTF8)
        return "bootstrap", report_bytes, hashlib.sha256(report_bytes).hexdigest()
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
    parser.add_argument("--bootstrap-notes-file", type=Path)
    parser.add_argument("--bootstrap-previous-tag")
    args = parser.parse_args(argv)
    try:
        attempt = load_attempt_identity(args.attempt)
        selection = InspectorSelection.model_validate_json(args.selection.read_bytes()) if args.selection else None
        bootstrap_notes = args.bootstrap_notes_file.read_text(encoding=_UTF8) if args.bootstrap_notes_file else None
        prepare_candidate(
            repo_root(),
            attempt,
            selection,
            args.version,
            args.output_directory,
            bootstrap_notes=bootstrap_notes,
            bootstrap_previous_tag=args.bootstrap_previous_tag,
        )
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

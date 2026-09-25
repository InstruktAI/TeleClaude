"""Publish a recorded commit through the internal documentation pipeline."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scripts.distribute import distribute_committed
from teleclaude.capabilities import Capabilities, resolve_capabilities
from teleclaude.docs_index import build_all_indexes, reroot_index_document
from teleclaude.docs_lock import DocsLeaseTimeoutError, DocsLockOperation, docs_lease
from teleclaude.docs_publishers import DocsPublisherResolutionError, git_common_root, publisher_resolution
from teleclaude.resource_validation import (
    _error,
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_all_snippets,
    validate_jobs_config,
)

_GIT_EXECUTABLE = "git"
_GIT_VERIFY_ARGS = ("rev-parse", "--verify", "--quiet")
_GIT_HEAD_ARGS = ("rev-parse", "HEAD")
_GIT_COMMIT_VERIFY_SUFFIX = "^{commit}"
_GIT_WORKTREE_ADD_ARGS = ("worktree", "add", "--detach")
_GIT_WORKTREE_REMOVE_ARGS = ("worktree", "remove", "--force")
_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_SNAPSHOT_DIRECTORY_PREFIX = "teleclaude-publication-"
_SNAPSHOT_SOURCE_DIRECTORY = "source"
_INVALID_COMMIT_ID = "Publication rejected an invalid recorded commit id."
_CANONICAL_OUTPUTS_SKIPPED = "Canonical checkout outputs skipped: recorded tip is not canonical HEAD."
_CANONICAL_OUTPUTS_RESTORED = "Canonical checkout outputs restored: canonical HEAD advanced during publication."
_CANONICAL_OUTPUTS_WRITTEN = "Canonical checkout outputs updated from the recorded commit."
_PUBLICATION_NEXT_SUFFIX = ".publication-next"
_PUBLICATION_RESTORE_SUFFIX = ".publication-restore"


def publish_recorded_commit(project_root: Path, after_sha: str) -> bool:
    """Publish one validated recorded commit through an isolated source worktree."""
    if _COMMIT_ID_PATTERN.fullmatch(after_sha) is None:
        print(_INVALID_COMMIT_ID, file=sys.stderr)
        return False
    canonical_root = git_common_root(project_root)
    try:
        resolved = subprocess.run(
            [_GIT_EXECUTABLE, *_GIT_VERIFY_ARGS, after_sha + _GIT_COMMIT_VERIFY_SUFFIX],
            cwd=canonical_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return False
    if resolved.returncode != 0 or resolved.stdout.strip() != after_sha:
        print(_INVALID_COMMIT_ID, file=sys.stderr)
        return False
    try:
        with docs_lease(DocsLockOperation.SYNCHRONIZATION):
            with _recorded_snapshot(canonical_root, after_sha) as snapshot_root:
                capabilities = resolve_capabilities(snapshot_root)
                if not capabilities.is_target:
                    return True
                findings = _collect_source_findings(snapshot_root, capabilities)
                if findings:
                    return False
                written = build_all_indexes(snapshot_root) if capabilities.docs else []
                index_outputs = [
                    (
                        source,
                        reroot_index_document(source.read_text(encoding="utf-8"), snapshot_root, canonical_root).encode(
                            "utf-8"
                        )
                        if source.is_file()
                        else None,
                    )
                    for source in written
                ]
                _install_canonical_files(snapshot_root, canonical_root, index_outputs, after_sha)
                distribution_outputs = distribute_committed(
                    snapshot_root,
                    canonical_root,
                    agents_enabled=capabilities.agents,
                    docs_enabled=capabilities.docs,
                )
                if distribution_outputs:
                    _install_canonical_files(
                        snapshot_root,
                        canonical_root,
                        [(source, source.read_bytes()) for source in distribution_outputs],
                        after_sha,
                    )
                return True
    except (DocsLeaseTimeoutError, subprocess.CalledProcessError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return False


@contextmanager
def _recorded_snapshot(canonical_root: Path, after_sha: str) -> Iterator[Path]:
    """Materialize a recorded source tree with access to the checkout's Python environment."""
    with tempfile.TemporaryDirectory(prefix=_SNAPSHOT_DIRECTORY_PREFIX) as temp_dir:
        snapshot_root = Path(temp_dir) / _SNAPSHOT_SOURCE_DIRECTORY
        subprocess.run(
            [_GIT_EXECUTABLE, *_GIT_WORKTREE_ADD_ARGS, str(snapshot_root), after_sha],
            cwd=canonical_root,
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            canonical_venv = canonical_root / ".venv"
            if canonical_venv.exists():
                (snapshot_root / ".venv").symlink_to(canonical_venv, target_is_directory=True)
            yield snapshot_root
        finally:
            subprocess.run(
                [_GIT_EXECUTABLE, *_GIT_WORKTREE_REMOVE_ARGS, str(snapshot_root)],
                cwd=canonical_root,
                check=False,
                capture_output=True,
                text=True,
            )


def _canonical_head(canonical_root: Path) -> str | None:
    """Read canonical HEAD as a full object id."""
    result = subprocess.run(
        [_GIT_EXECUTABLE, *_GIT_HEAD_ARGS],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _install_canonical_files(
    snapshot_root: Path,
    canonical_root: Path,
    outputs: list[tuple[Path, bytes | None]],
    after_sha: str,
) -> None:
    """Atomically install snapshot outputs only while their recorded tip is canonical."""
    if _canonical_head(canonical_root) != after_sha:
        print(_CANONICAL_OUTPUTS_SKIPPED)
        return
    previous: dict[Path, bytes | None] = {}
    staged: list[tuple[Path, Path | None]] = []
    for source, payload in outputs:
        destination = canonical_root / source.relative_to(snapshot_root)
        previous_payload = destination.read_bytes() if destination.is_file() else None
        previous[destination] = previous_payload
        if payload is not None:
            if payload == previous_payload:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + _PUBLICATION_NEXT_SUFFIX)
            temporary.write_bytes(payload)
            staged.append((destination, temporary))
        elif previous_payload is not None:
            staged.append((destination, None))
    for destination, temporary in staged:
        if temporary is None:
            destination.unlink(missing_ok=True)
        else:
            os.replace(temporary, destination)
    if _canonical_head(canonical_root) == after_sha:
        print(_CANONICAL_OUTPUTS_WRITTEN)
        return
    for destination, payload in previous.items():
        if payload is None:
            destination.unlink(missing_ok=True)
            continue
        temporary = destination.with_name(destination.name + _PUBLICATION_RESTORE_SUFFIX)
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    print(_CANONICAL_OUTPUTS_RESTORED)


def _group_findings(findings: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Group validation findings by code and reason."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for finding in findings:
        path = finding.get("path", "")
        if not path:
            continue
        code = finding["code"]
        reason = finding.get("reason", "")
        grouped.setdefault(code, {}).setdefault(reason, []).append(path)
    return grouped


def _collect_source_findings(project_root: Path, capabilities: Capabilities) -> list[str]:
    """Run the snippet, artifact, and jobs-config validators; print and return findings."""
    clear_errors()
    errors: list[str] = []
    try:
        with publisher_resolution(project_root):
            if capabilities.docs:
                validate_all_snippets(project_root)
            if capabilities.agents:
                errors.extend(validate_all_artifacts(project_root))
    except DocsPublisherResolutionError as exc:
        _error("snippet_global_source_resolution_failed", path=str(project_root), reason=str(exc))
    errors.extend(validate_jobs_config(project_root))
    findings = get_errors()
    if findings:
        _print_findings(findings, quiet=False)
        errors.extend(_format_finding(finding) for finding in findings)
    for error in errors:
        print(error)
    return errors


def _format_finding(finding: dict[str, str]) -> str:
    """Format one validation finding without dropping diagnostic fields."""
    extras = ", ".join(f"{key}={value}" for key, value in finding.items() if key not in {"code", "path"})
    if extras:
        return f"{finding['code']}: {finding['path']} ({extras})"
    return f"{finding['code']}: {finding['path']}"


def _print_findings(findings: list[dict[str, str]], *, quiet: bool) -> None:
    """Print validation findings grouped by code and reason."""
    if not findings:
        return
    print(f"Validation findings: {len(findings)}")
    if quiet:
        return
    for code, reason_groups in _group_findings(findings).items():
        no_reason = reason_groups.get("", [])
        if no_reason:
            print(f"{code}:")
            for path in no_reason:
                print(f"- {path}")
        for reason, paths in reason_groups.items():
            if not reason:
                continue
            print(f"{code}/{reason}:")
            for path in paths:
                print(f"- {path}")

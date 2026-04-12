"""Orchestrate validation, index building, and artifact distribution.

Entry point for ``telec sync``. Replaces the old sync_resources.py + distribute.py
two-step pipeline with a single idempotent operation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from teleclaude.docs_index import build_all_indexes
from teleclaude.paths import REPO_ROOT
from teleclaude.resource_validation import (
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_all_snippets,
    validate_jobs_config,
    validate_third_party_docs,
)


def sync(
    project_root: Path,
    *,
    validate_only: bool = False,
    warn_only: bool = False,
) -> bool:
    """Run the full sync pipeline: validate → build indexes → distribute artifacts.

    Returns True if successful, False if validation errors occurred.
    """
    if not validate_only:
        _repair_broken_docs_links(project_root)
    clear_errors()
    errors: list[str] = []

    # Phase 1: Validate
    validate_all_snippets(project_root)
    validate_third_party_docs(project_root)
    artifact_errors = validate_all_artifacts(project_root)
    errors.extend(artifact_errors)
    errors.extend(validate_jobs_config(project_root))
    findings = get_errors()
    if findings:
        _print_findings(findings, quiet=warn_only)
        errors.extend(
            (
                f"{finding['code']}: {finding['path']} "
                f"(ref={finding.get('ref', '')} expected={finding.get('expected', '')})"
            )
            for finding in findings
        )

    if errors:
        for error in errors:
            print(error)
        if not warn_only:
            return False

    if validate_only:
        return warn_only or not errors

    # Phase 2: Build indexes
    written = build_all_indexes(project_root)
    for path in written:
        if path.exists():
            print(f"Index: {path}")
    _repair_broken_docs_links(project_root)

    # Phase 3: Build and deploy artifacts
    _run_distribute(project_root, warn_only=warn_only)
    _repair_broken_docs_links(project_root)

    return True


def _run_distribute(project_root: Path, *, warn_only: bool) -> None:
    """Run distribute.py to transpile and deploy artifacts."""
    script_path = REPO_ROOT / "scripts" / "distribute.py"
    if not script_path.exists():
        return

    cmd = [
        sys.executable,
        str(script_path),
        "--project-root",
        str(project_root),
        "--deploy",
    ]
    if warn_only:
        cmd.append("--warn-only")

    env = os.environ.copy()
    subprocess.run(cmd, cwd=project_root, check=not warn_only, env=env)


def _repair_broken_docs_links(project_root: Path) -> None:
    """Repair known self-referential docs symlink corruption in-place.

    Some local watcher/filter failure modes can turn tracked files like
    ``docs/global/baseline.md`` into self-pointing symlinks
    (``baseline.md -> .../baseline.md``), which then breaks sync with
    ``Too many levels of symbolic links``.
    """
    tracked_docs_files = ("docs/global/baseline.md",)
    for rel_path in tracked_docs_files:
        file_path = project_root / rel_path
        needs_repair = False
        if not file_path.exists():
            needs_repair = True
        elif file_path.is_symlink():
            try:
                raw_target = os.readlink(file_path)
            except OSError:
                raw_target = ""
            target_path = Path(raw_target)
            if not target_path.is_absolute():
                target_path = (file_path.parent / target_path).resolve(strict=False)
            # Repair if link is broken or points to itself.
            needs_repair = (not file_path.exists()) or (target_path == file_path)

        if not needs_repair:
            continue

        from teleclaude.git import GitCommandError, Repo  # pylint: disable=import-outside-toplevel

        try:
            repo = Repo(str(project_root))
            blob_content = repo.git.show(f"HEAD:{rel_path}")
        except (GitCommandError, OSError):
            continue

        file_path.unlink(missing_ok=True)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(blob_content, encoding="utf-8")


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

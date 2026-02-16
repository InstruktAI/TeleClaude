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
    clear_warnings,
    get_warnings,
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
    clear_warnings()
    errors: list[str] = []

    # Phase 1: Validate
    validate_all_snippets(project_root)
    validate_third_party_docs(project_root)
    artifact_errors = validate_all_artifacts(project_root)
    errors.extend(artifact_errors)
    errors.extend(validate_jobs_config(project_root))

    warnings = get_warnings()
    if warnings:
        _print_warnings(warnings, quiet=warn_only)

    if errors:
        for error in errors:
            print(error)
        if not warn_only:
            return False

    if validate_only:
        return len(errors) == 0

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
    tracked_docs_files = (
        "docs/global/baseline.md",
        "docs/global/index.yaml",
    )
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

        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if blob.returncode != 0:
            continue

        file_path.unlink(missing_ok=True)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(blob.stdout, encoding="utf-8")


def _print_warnings(warnings: list[dict[str, str]], *, quiet: bool) -> None:
    """Print validation warnings grouped by code."""
    if not warnings:
        return
    print(f"Validation warnings: {len(warnings)}")
    if quiet:
        return
    grouped: dict[str, list[dict[str, str]]] = {}
    for warning in warnings:
        grouped.setdefault(warning["code"], []).append(warning)
    for code, items in grouped.items():
        reason_groups: dict[str, list[str]] = {}
        no_reason: list[str] = []
        for warning in items:
            path = warning.get("path", "")
            if not path:
                continue
            reason = warning.get("reason")
            if reason:
                reason_groups.setdefault(reason, []).append(path)
            else:
                no_reason.append(path)
        if no_reason:
            print(f"{code}:")
            for path in no_reason:
                print(f"- {path}")
        for reason, paths in reason_groups.items():
            print(f"{code}/{reason}:")
            for path in paths:
                print(f"- {path}")

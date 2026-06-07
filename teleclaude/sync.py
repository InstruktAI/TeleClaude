"""Orchestrate validation, index building, and artifact distribution.

Entry point for ``telec sync``. Replaces the old sync_resources.py + distribute.py
two-step pipeline with a single idempotent operation.
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from teleclaude.docs_index import build_all_indexes
from teleclaude.docs_reconcile import _delivered_by, _iter_snippet_files, _split_frontmatter
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT
from teleclaude.project_setup.git_filters import ensure_git_filters
from teleclaude.resource_validation import (
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_all_snippets,
    validate_jobs_config,
)


@dataclass(frozen=True)
class SnippetProvenanceRecord:
    """A snippet delivered_by membership anchored to the current git HEAD."""

    snippet_path: str
    slug: str
    head_sha_at_acquisition: str


def sync(
    project_root: Path,
    *,
    skip_deploy: bool = False,
    skip_validation: bool = False,
) -> bool:
    """Run the sync pipeline over its two phases: validate, then deploy.

    Validation always blocks — any finding returns ``False`` and stops the pipeline.
    The two flags each skip one phase:

    - ``skip_deploy``: validate only, do not build/distribute. The read-only gate for
      pre-commit / CI / lint — it must not mutate the host's agent-runtime dirs.
    - ``skip_validation``: skip validation entirely and deploy without blocking. The
      live-reload path for the docs watcher (and bootstrap setup); NOT for agents.

    Returns ``True`` on success, ``False`` if validation found errors.
    """
    # Phase 0: Self-heal the docs git filter. The smudge/clean driver lives in
    # per-clone .git/config, so a fresh checkout has the .gitattributes rule but
    # no driver — smudge silently no-ops and the validation below reads unexpanded
    # paths. Configure the driver and re-smudge stale docs before anything reads them.
    ensure_git_filters(project_root)

    # Phase 1: Validate (always blocks — there is no warn-and-pass mode).
    if not skip_validation:
        clear_errors()
        errors: list[str] = []
        validate_all_snippets(project_root)
        errors.extend(validate_all_artifacts(project_root))
        errors.extend(validate_jobs_config(project_root))
        findings = get_errors()
        if findings:
            _print_findings(findings, quiet=False)
            errors.extend(_format_finding(finding) for finding in findings)
        if errors:
            for error in errors:
                print(error)
            return False

    if skip_deploy:
        return True

    # Phase 2: Record provenance
    _record_snippet_provenance_from_environment(project_root)

    # Phase 3: Build indexes
    written = build_all_indexes(project_root)
    for path in written:
        if path.exists():
            print(f"Index: {path}")

    # Phase 4: Build and deploy artifacts
    _run_distribute(project_root)

    return True


def _record_snippet_provenance_from_environment(project_root: Path) -> int:
    """Record first-acquisition provenance for snippet delivered_by slugs."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return 0

    try:
        repo = Repo(project_root, search_parent_directories=True)
        head_sha = repo.head.commit.hexsha
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError, ValueError):
        return 0
    return _record_snippet_provenance(project_root, head_sha, database_url)


def _record_snippet_provenance(project_root: Path, head_sha: str, database_url: str) -> int:
    """Insert provenance rows for every current snippet delivered_by membership."""
    records = _collect_snippet_provenance_records(project_root, head_sha)
    if not records:
        return 0
    try:
        _run_psql_snippet_provenance_import(
            database_url,
            _render_snippet_provenance_import_script(records),
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"Warning: snippet provenance import skipped: psql exited with status {exc.returncode}",
            file=sys.stderr,
        )
        return 0
    except OSError as exc:
        print(f"Warning: snippet provenance import skipped: {exc}", file=sys.stderr)
        return 0
    return len(records)


def _render_snippet_provenance_import_script(records: list[SnippetProvenanceRecord]) -> str:
    """Render a psql COPY script that preserves existing provenance anchors."""
    buf = io.StringIO()
    buf.write("begin;\n")
    buf.write(
        "create temporary table snippet_provenance_import "
        "(snippet_path text, slug text, head_sha_at_acquisition text) on commit drop;\n"
    )
    buf.write(
        "copy snippet_provenance_import (snippet_path, slug, head_sha_at_acquisition) from stdin with (format csv);\n"
    )
    writer = csv.writer(buf, lineterminator="\n")
    for record in records:
        writer.writerow([record.snippet_path, record.slug, record.head_sha_at_acquisition])
    buf.write("\\.\n")
    buf.write(
        "insert into workflow.snippet_provenance "
        "(snippet_path, slug, head_sha_at_acquisition) "
        "select snippet_path, slug, head_sha_at_acquisition from snippet_provenance_import "
        "on conflict (snippet_path, slug) do nothing;\n"
    )
    buf.write("commit;\n")
    return buf.getvalue()


def _run_psql_snippet_provenance_import(database_url: str, script: str) -> None:
    """Run provenance import through psql.

    The Python runtime intentionally does not depend on a PostgreSQL DBAPI
    driver; `psql` is the available native workflow database boundary here.
    """
    subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1"],
        input=script,
        text=True,
        check=True,
    )


def _collect_snippet_provenance_records(project_root: Path, head_sha: str) -> list[SnippetProvenanceRecord]:
    """Collect delivered_by memberships from snippet frontmatter."""
    records: list[SnippetProvenanceRecord] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, _body = parsed
        try:
            relative_path = snippet_path.relative_to(project_root).as_posix()
        except ValueError:
            relative_path = snippet_path.as_posix()
        for slug in _delivered_by(metadata):
            records.append(
                SnippetProvenanceRecord(
                    snippet_path=relative_path,
                    slug=slug,
                    head_sha_at_acquisition=head_sha,
                )
            )
    return records


def _run_distribute(project_root: Path) -> None:
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

    env = os.environ.copy()
    subprocess.run(cmd, cwd=project_root, check=True, env=env)


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

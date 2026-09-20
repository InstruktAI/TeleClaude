"""Orchestrate validation, index building, and artifact distribution.

Entry point for ``telec sync``. Replaces the old sync_resources.py + distribute.py
two-step pipeline with a single idempotent operation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from teleclaude.capabilities import Capabilities, resolve_capabilities
from teleclaude.docs_index import build_all_indexes
from teleclaude.docs_lock import DocsLeaseTimeoutError, DocsLockOperation, docs_lease
from teleclaude.docs_publishers import DocsPublisherResolutionError, publisher_resolution
from teleclaude.paths import REPO_ROOT
from teleclaude.resource_validation import (
    _error,
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_all_snippets,
    validate_jobs_config,
)

_DISTRIBUTE_AGENTS_ENABLED_FLAG = "--agents-enabled"
_DISTRIBUTE_AGENTS_DISABLED_FLAG = "--no-agents-enabled"
_DISTRIBUTE_DOCS_ENABLED_FLAG = "--docs-enabled"
_DISTRIBUTE_DOCS_DISABLED_FLAG = "--no-docs-enabled"


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
    - ``skip_validation``: skip the validate phase and deploy without blocking. The
      docs watcher's live-reload path, and the deploy leg of :func:`sync_bootstrap`
      (which validates non-blocking first). NOT an agent-facing bypass.

    Returns ``True`` on success, ``False`` if validation found errors.
    """
    capabilities = resolve_capabilities(project_root)
    if not capabilities.is_target:
        return True

    if skip_deploy:
        # Validation resolves every reference from publisher sources and never reads
        # the deployed tree, so it holds no lease and never waits behind a deploy.
        return skip_validation or not _collect_source_findings(project_root, capabilities)
    try:
        with docs_lease(DocsLockOperation.SYNCHRONIZATION) as lock_descriptor:
            return _sync_locked(
                project_root,
                capabilities,
                skip_validation=skip_validation,
                lock_descriptor=lock_descriptor,
            )
    except DocsLeaseTimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return False


def _sync_locked(
    project_root: Path,
    capabilities: Capabilities,
    *,
    skip_validation: bool,
    lock_descriptor: int,
) -> bool:
    """Run one deploying synchronization pipeline while its documentation lease is held."""

    # Phase 1: Validate. The telec sync command always blocks on findings; only the
    # watcher's live-reload passes skip_validation to omit the phase entirely.
    if not skip_validation and _collect_source_findings(project_root, capabilities):
        return False

    # Phase 2: Build indexes
    if capabilities.docs:
        written = build_all_indexes(project_root)
        for path in written:
            if path.exists():
                print(f"Index: {path}")

    # Phase 3: Build and deploy artifacts
    _run_distribute(project_root, capabilities, lock_descriptor=lock_descriptor)

    return True


def sync_bootstrap(project_root: Path) -> None:
    """Validate-and-report (non-blocking), then deploy. The project-bootstrap path.

    Project bootstrap — ``telec projects init`` / ``onboard`` — is a human-run, one-time
    setup, not an agent-facing recurring gate. It surfaces validation findings for the
    human watching, then completes setup regardless, so onboarding a project that already
    carries findings is never blocked. The commit gate enforces validation once real work
    begins.
    """
    capabilities = resolve_capabilities(project_root)
    if not capabilities.is_target:
        return
    try:
        with docs_lease(DocsLockOperation.SYNCHRONIZATION) as lock_descriptor:
            _collect_source_findings(project_root, capabilities)
            _sync_locked(
                project_root,
                capabilities,
                skip_validation=True,
                lock_descriptor=lock_descriptor,
            )
    except DocsLeaseTimeoutError as exc:
        print(str(exc), file=sys.stderr)


def _run_distribute(project_root: Path, capabilities: Capabilities, *, lock_descriptor: int) -> None:
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
        _DISTRIBUTE_AGENTS_ENABLED_FLAG if capabilities.agents else _DISTRIBUTE_AGENTS_DISABLED_FLAG,
        _DISTRIBUTE_DOCS_ENABLED_FLAG if capabilities.docs else _DISTRIBUTE_DOCS_DISABLED_FLAG,
    ]

    env = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    subprocess.run(cmd, cwd=project_root, check=True, env=env, pass_fds=(lock_descriptor,))


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
    """Run the snippet, artifact, and jobs-config validators; print findings; return them.

    Single owner of the source-validation sequence. Callers decide whether findings
    block: :func:`sync` aborts on a non-empty result, :func:`sync_bootstrap` reports
    and continues.
    """
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

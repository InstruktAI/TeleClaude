"""Job subcommand handlers for telec jobs <subcommand>."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from jobs.base import JobResult
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import JOBS_REPORT
from teleclaude.config.jobs import load_effective_jobs
from teleclaude.paths import JOBS_DIR
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.session_identity import get_session_id

_JOB_NAME_REQUIRED_ERROR: Final[str] = "Error: job name required"


def handle_jobs(args: list[str]) -> None:
    """Handle telec jobs <subcommand> [args]."""
    if not args or args[0] in ("-h", "--help"):
        _jobs_help()
        return

    subcommand = args[0]
    rest = args[1:]
    if subcommand == "report":
        handle_jobs_report(rest)
        return

    print(f"Unknown jobs subcommand: {subcommand}", file=sys.stderr)
    print("Run 'telec jobs --help' for usage.", file=sys.stderr)
    raise SystemExit(1)


def handle_jobs_report(args: list[str]) -> None:
    """Write a structured JobResult record for a configured recurring job.

    Usage: telec jobs report <name> --success true|false --message <text>
                             [--items-processed <n>] [--error <text> ...]

    <name> is the job's declared identity for both agent and script jobs.
    """
    parsed = parse_command_args(JOBS_REPORT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    job_name = positionals[0] if positionals else None
    if not job_name:
        print(_JOB_NAME_REQUIRED_ERROR, file=sys.stderr)
        raise SystemExit(1)

    success_raw = parsed.value(F.FLAG_JOB_SUCCESS)
    message = parsed.value(F.FLAG_JOB_MESSAGE)
    items_processed_raw = parsed.value(F.FLAG_JOB_ITEMS_PROCESSED)
    errors = list(parsed.values(F.FLAG_JOB_ERROR))

    if success_raw is None:
        print("Error: --success is required", file=sys.stderr)
        raise SystemExit(1)
    success = _parse_bool(success_raw)
    if message is None:
        print("Error: --message is required", file=sys.stderr)
        raise SystemExit(1)
    items_processed = _parse_non_negative_int(items_processed_raw) if items_processed_raw is not None else 0

    project_root = _report_project_root()
    project_slug = _current_project_slug(project_root)
    _validate_known_job(job_name, project_root)
    runs_dir = _contained_runs_dir(_project_job_key(project_slug, job_name))
    runs_dir.mkdir(parents=True, exist_ok=True)

    result = JobResult(
        success=success,
        message=message,
        items_processed=items_processed,
        errors=errors or None,
        session_id=get_session_id(),
    )
    record_path = runs_dir / _record_filename()
    record_path.write_text(result.to_json() + "\n", encoding="utf-8")

    print(json.dumps({"status": "ok", "path": str(record_path)}, ensure_ascii=True))


def _jobs_help() -> None:
    print(
        """Usage: telec jobs <subcommand> [args]

Subcommands:
  report  Write a structured recurring job result record

Run 'telec jobs <subcommand> --help' for subcommand-specific help."""
    )


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    print("Error: --success must be true or false", file=sys.stderr)
    raise SystemExit(1)


def _parse_non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        print("Error: --items-processed must be an integer", file=sys.stderr)
        raise SystemExit(1) from exc
    if value < 0:
        print("Error: --items-processed must be non-negative", file=sys.stderr)
        raise SystemExit(1)
    return value


def _validate_known_job(job_name: str, project_root: Path) -> None:
    if job_name not in _load_known_job_names(project_root):
        print(f"Error: unknown job: {job_name}", file=sys.stderr)
        raise SystemExit(1)


def _load_known_job_names(project_root: Path) -> set[str]:
    return {job.identity for job in load_effective_jobs(project_root)}


def _report_project_root() -> Path:
    return resolve_invocation_roots().require_project_root()


def _current_project_slug(project_root: Path) -> str:
    project = get_project_catalog_service().get_by_root(project_root)
    if project is None:
        raise ValueError(f"reporting project is not registered: {project_root}")
    return project.slug


def _project_job_key(project_slug: str, job_name: str) -> str:
    return f"{project_slug}:{job_name}"


def _contained_runs_dir(job_name: str) -> Path:
    root = JOBS_DIR.resolve(strict=False)
    runs_dir = (root / job_name / "runs").resolve(strict=False)
    try:
        runs_dir.relative_to(root)
    except ValueError as exc:
        print("Error: job_id resolves outside the jobs directory", file=sys.stderr)
        raise SystemExit(1) from exc
    return runs_dir


def _record_filename() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"

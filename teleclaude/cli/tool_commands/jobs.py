"""Job subcommand handlers for telec jobs <subcommand>."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from jobs.base import JobResult
from teleclaude.config.loader import load_project_config
from teleclaude.paths import JOBS_DIR, REPO_ROOT, ConfigFileName


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

    Usage: telec jobs report <job_name> --success true|false --message <text>
                             [--items-processed <n>] [--error <text> ...]
    """
    if "--help" in args or "-h" in args:
        print(handle_jobs_report.__doc__ or "")
        return

    job_name, remaining = _parse_job_name(args)
    success: bool | None = None
    message: str | None = None
    items_processed = 0
    errors: list[str] = []

    index = 0
    while index < len(remaining):
        token = remaining[index]
        if token == "--success" and index + 1 < len(remaining):
            success = _parse_bool(remaining[index + 1])
            index += 2
        elif token == "--message" and index + 1 < len(remaining):
            message = remaining[index + 1]
            index += 2
        elif token == "--items-processed" and index + 1 < len(remaining):
            items_processed = _parse_non_negative_int(remaining[index + 1])
            index += 2
        elif token == "--error" and index + 1 < len(remaining):
            errors.append(remaining[index + 1])
            index += 2
        else:
            print(f"Error: unknown or incomplete argument: {token}", file=sys.stderr)
            raise SystemExit(1)

    if success is None:
        print("Error: --success is required", file=sys.stderr)
        raise SystemExit(1)
    if message is None:
        print("Error: --message is required", file=sys.stderr)
        raise SystemExit(1)

    _validate_known_job(job_name)
    runs_dir = _contained_runs_dir(job_name)
    runs_dir.mkdir(parents=True, exist_ok=True)

    result = JobResult(
        success=success,
        message=message,
        items_processed=items_processed,
        errors=errors or None,
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


def _parse_job_name(args: list[str]) -> tuple[str, list[str]]:
    if not args or args[0].startswith("-"):
        print("Error: job_name required", file=sys.stderr)
        raise SystemExit(1)
    return args[0], args[1:]


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


def _validate_known_job(job_name: str) -> None:
    if job_name not in _load_known_job_names():
        print(f"Error: unknown job: {job_name}", file=sys.stderr)
        raise SystemExit(1)


def _load_known_job_names() -> set[str]:
    config = load_project_config(REPO_ROOT / ConfigFileName.OVERLAY)
    return set(config.jobs)


def _contained_runs_dir(job_name: str) -> Path:
    root = JOBS_DIR.resolve(strict=False)
    runs_dir = (root / job_name / "runs").resolve(strict=False)
    try:
        runs_dir.relative_to(root)
    except ValueError as exc:
        print("Error: job_name resolves outside the jobs directory", file=sys.stderr)
        raise SystemExit(1) from exc
    return runs_dir


def _record_filename() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"

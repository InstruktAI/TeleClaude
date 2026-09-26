#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
#     "pydantic",
#     "instruktai-python-logger",
# ]
# ///
"""
Cron runner - executes scheduled jobs.

This script is designed to be symlinked to ~/.teleclaude/scripts/ and called
by launchd on an hourly schedule. It reads configured jobs from teleclaude.yml
and runs those that are due based on their schedules.

Usage:
    cron_runner.py              # Run all due jobs
    cron_runner.py --force      # Run all jobs regardless of schedule
    cron_runner.py --job NAME   # Run specific job only
    cron_runner.py --dry-run    # Check what would run
    cron_runner.py --list       # List available jobs
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from instrukt_ai_logging import configure_logging, get_logger

_SCRIPT_PATH = Path(__file__).resolve()
_REPO_ROOT = _SCRIPT_PATH.parents[1]
_PROJECT_ENV = _REPO_ROOT / ".venv"
_PROJECT_PYTHON = _PROJECT_ENV / "bin" / "python"
_REQUIRED_MODULES = ("teleclaude", "jobs.base")
_RUNTIME_ERROR = (
    "cron_runner requires the installed project runtime at {interpreter}. "
    "Create it with `uv sync --project {project_root}`."
)
_PACKAGE_ERROR = (
    "cron_runner cannot import required project packages: {modules}. "
    "Refresh the project environment with `uv sync --project {project_root}`."
)
_PACKAGE_IMPORT_ERROR = (
    "cron_runner cannot import the project runtime: {error}. "
    "Refresh the project environment with `uv sync --project {project_root}`."
)


def _prepare_project_runtime() -> None:
    if not _PROJECT_PYTHON.is_file() or not os.access(_PROJECT_PYTHON, os.X_OK):
        print(
            _RUNTIME_ERROR.format(interpreter=_PROJECT_PYTHON, project_root=_REPO_ROOT),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if Path(sys.prefix).resolve() == _PROJECT_ENV.resolve():
        return

    # PEP 723 uv execution is isolated from the installed first-party packages.
    # Replacing this process is required to enter their project-owned runtime;
    # no in-process import or shell command can supply that environment.
    os.execv(str(_PROJECT_PYTHON), [str(_PROJECT_PYTHON), *sys.argv])


def _preflight_project_packages() -> None:
    missing: list[str] = []
    for module_name in _REQUIRED_MODULES:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            module_spec = None
        if module_spec is None:
            missing.append(module_name)

    if missing:
        print(
            _PACKAGE_ERROR.format(modules=", ".join(missing), project_root=_REPO_ROOT),
            file=sys.stderr,
        )
        raise SystemExit(1)


_prepare_project_runtime()
_preflight_project_packages()

# Configure logging before imported modules run startup code so this process
# writes its own per-source file (cron.log) rather than mixing into the daemon's
# teleclaude.log. Runtime import failures are logged here and reported with an
# actionable startup diagnostic below.
configure_logging("teleclaude", source="cron")
logger = get_logger(__name__)

try:
    from teleclaude.config.jobs import (
        load_effective_jobs,
    )
    from teleclaude.cron.runner import (
        load_job_state,
        run_due_jobs,
    )
    from teleclaude.services.project_catalog import (
        get_project_catalog_service,
    )
except ImportError as exc:
    logger.exception("cron_runner_project_import_failed")
    print(
        _PACKAGE_IMPORT_ERROR.format(error=exc, project_root=_REPO_ROOT),
        file=sys.stderr,
    )
    raise SystemExit(1) from None


def _describe_schedule(schedule: object) -> str:
    when = getattr(schedule, "when", None)
    if when is not None:
        every = getattr(when, "every", None)
        if every:
            return f"every {every}"
        at = getattr(when, "at", None)
        if isinstance(at, list):
            return ", ".join(f"at {item}" for item in at)
        if at:
            return f"at {at}"
    schedule_str = getattr(schedule, "schedule", None)
    return schedule_str or "none"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run scheduled jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run jobs regardless of schedule",
    )
    parser.add_argument(
        "--job",
        metavar="NAME",
        help="Run only the specified job",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check what would run without executing",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_jobs",
        help="List available jobs and their status",
    )
    args = parser.parse_args()

    if args.list_jobs:
        catalog = get_project_catalog_service()
        catalog.refresh()
        state = load_job_state(catalog)
        jobs = [(project.slug, job) for project in catalog.list_projects() for job in load_effective_jobs(project.root)]

        if not jobs:
            print("No jobs found")
            return 0

        print(f"{'Job':<60} {'Type':<8} {'Schedule':<10} {'Last Run':<25} {'Status':<10}")
        print("-" * 118)

        for project_slug, job in jobs:
            job_key = f"{project_slug}:{job.identity}"
            job_state = state.get_job(job_key)
            schedule_str = _describe_schedule(job.declaration)
            last_run = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else "never"
            job_type = "agent" if job.declaration.job else "script"
            print(f"{job_key:<60} {job_type:<8} {schedule_str:<10} {last_run:<25} {job_state.last_status:<10}")

        return 0

    logger.info("cron runner starting", force=args.force, dry_run=args.dry_run)

    results = run_due_jobs(
        force=args.force,
        job_filter=args.job,
        dry_run=args.dry_run,
    )

    if not results:
        logger.info("no jobs ran")
        return 0

    success_count = sum(1 for v in results.values() if v)
    fail_count = len(results) - success_count

    logger.info(
        "cron runner complete",
        jobs_run=len(results),
        success=success_count,
        failed=fail_count,
    )

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

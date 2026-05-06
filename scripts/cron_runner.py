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
import sys
from pathlib import Path

# Allow running from any working directory by anchoring imports at repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Configure logging FIRST, before any heavy import. Two reasons:
# (1) so this process writes its own per-source file (cron.log) rather than
#     mixing into the daemon's teleclaude.log; (2) so any ImportError below
#     surfaces through the central logger instead of escaping to stderr —
#     which used to land in a launchd StandardErrorPath sidechannel that
#     `instrukt-ai-logs teleclaude` did not read.
from instrukt_ai_logging import configure_logging, get_logger

configure_logging("teleclaude", source="cron")
logger = get_logger(__name__)

try:
    from teleclaude.cron.runner import _load_job_schedules, discover_jobs, run_due_jobs
    from teleclaude.cron.state import CronState
except Exception:
    logger.exception("cron_runner failed during import")
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
        python_jobs = discover_jobs()
        state = CronState.load()
        schedules = _load_job_schedules()

        # Build unified list: Python jobs + agent jobs from config
        python_job_names = {job.name for job in python_jobs}
        agent_job_names = [
            name for name, cfg in schedules.items() if cfg.type == "agent" and name not in python_job_names
        ]

        if not python_jobs and not agent_job_names:
            print("No jobs found")
            return 0

        print(f"{'Job':<30} {'Type':<8} {'Schedule':<10} {'Last Run':<25} {'Status':<10}")
        print("-" * 88)

        for job in python_jobs:
            job_state = state.get_job(job.name)
            sched = schedules.get(job.name)
            schedule_str = _describe_schedule(sched) if sched else "none"
            last_run = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else "never"
            print(f"{job.name:<30} {'script':<8} {schedule_str:<10} {last_run:<25} {job_state.last_status:<10}")

        for name in agent_job_names:
            job_state = state.get_job(name)
            sched = schedules[name]
            schedule_str = _describe_schedule(sched)
            last_run = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else "never"
            print(f"{name:<30} {'agent':<8} {schedule_str:<10} {last_run:<25} {job_state.last_status:<10}")

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

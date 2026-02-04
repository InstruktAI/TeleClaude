"""YouTube subscription sync job."""

from __future__ import annotations

import sys
from pathlib import Path

from jobs.base import Job, JobResult, Schedule

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.cron.discovery import discover_youtube_subscribers
from teleclaude.tagging.youtube import sync_youtube_subscriptions


class YouTubeSyncJob(Job):
    """
    Sync and tag YouTube subscriptions for all configured subscribers.

    Discovers all scopes (global + people) with subscriptions.youtube configured
    and runs tagging for each.
    """

    name = "youtube_sync"
    schedule = Schedule.DAILY
    preferred_hour = 6

    def __init__(
        self,
        *,
        mode: str = "normal+web",
        thinking_mode: str = "fast",
        refresh: bool = False,
    ):
        self.mode = mode
        self.thinking_mode = thinking_mode
        self.refresh = refresh

    def run(self) -> JobResult:
        """Execute YouTube sync for all subscribers."""
        subscribers = discover_youtube_subscribers()

        if not subscribers:
            return JobResult(
                success=True,
                message="No YouTube subscribers configured",
                items_processed=0,
            )

        total_processed = 0
        errors: list[str] = []

        for sub in subscribers:
            try:
                result = sync_youtube_subscriptions(
                    subscriber=sub,
                    mode=self.mode,
                    thinking_mode=self.thinking_mode,
                    refresh=self.refresh,
                )
                total_processed += result.channels_updated
            except Exception as e:
                scope_name = sub.name or "global"
                errors.append(f"{scope_name}: {e}")

        success = len(errors) == 0
        message = (
            f"Synced {len(subscribers)} subscriber(s), {total_processed} channels updated"
            if success
            else f"Completed with {len(errors)} error(s)"
        )

        return JobResult(
            success=success,
            message=message,
            items_processed=total_processed,
            errors=errors if errors else None,
        )


# Job instance for discovery by runner
JOB = YouTubeSyncJob()

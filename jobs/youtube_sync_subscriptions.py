"""Nightly YouTube subscription tagger.

Discovers all people (and global scope) with YouTube subscriptions configured
in their teleclaude.yml, reads each subscriber's youtube.csv, and uses AI agents
to classify any channels that don't have tags yet. Already-tagged channels are
skipped entirely.

The tagging pipeline: enrich untagged channels with About page descriptions,
send batches to AI agents (Claude/Codex/Gemini via round-robin) with the
subscriber's allowed tag list, validate responses, and fall back to web research
for channels the normal pass couldn't classify.

Integration:
- Called by the cron runner (scripts/cron_runner.py) on a daily schedule.
- Uses teleclaude/cron/discovery.py to find subscribers.
- Delegates all tagging logic to teleclaude/tagging/youtube.py.
- Per-person config: ~/.teleclaude/people/{name}/teleclaude.yml
- Per-person data: ~/.teleclaude/people/{name}/subscriptions/youtube.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

from jobs.base import Job, JobResult

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

    name = "youtube_sync_subscriptions"

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

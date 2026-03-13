"""Tag-filtered YouTube channel scraper job.

Reads each subscriber's youtube.csv, selects channels whose tags intersect
with the job's configured ``tags`` filter list, and fetches recent video
metadata for each matching channel using the existing YouTube search helper.

Integration:
- Called by the cron runner (scripts/cron_runner.py) on a daily schedule.
- Config key: ``jobs.youtube_scraper`` in teleclaude.yml.
- Uses teleclaude/cron/discovery.py to find subscribers.
- Reads channel rows from teleclaude/tagging/youtube.py.
- Fetches video metadata via teleclaude/helpers/youtube_helper.py.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from jobs.base import Job, JobResult

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.config.loader import load_project_config
from teleclaude.cron.discovery import Subscriber, discover_youtube_subscribers
from teleclaude.helpers.youtube_helper import Video, youtube_search
from teleclaude.tagging.youtube import ChannelRow, read_csv

logger = get_logger(__name__)

_DEFAULT_PERIOD_DAYS = 7


def filter_channels_by_tags(rows: list[ChannelRow], job_tags: list[str]) -> list[ChannelRow]:
    """Return rows whose tags intersect with ``job_tags``.

    Channels with empty tags or only ``n/a`` are excluded.
    """
    if not job_tags:
        return []
    tag_set = set(job_tags)
    matched = []
    for row in rows:
        raw = row.tags.strip()
        if not raw or raw == "n/a":
            continue
        channel_tags = {t.strip() for t in raw.split(",") if t.strip() and t.strip() != "n/a"}
        if channel_tags & tag_set:
            matched.append(row)
    return matched


class YouTubeScraperJob(Job):
    """Fetch recent videos for tag-filtered subscribed YouTube channels.

    For each subscriber, reads their youtube.csv and selects channels whose
    tags intersect with the job's ``tags`` config list, then fetches recent
    video metadata per matching channel.
    """

    name = "youtube_scraper"

    def __init__(self, *, period_days: int = _DEFAULT_PERIOD_DAYS):
        self.period_days = period_days

    def _job_tags(self) -> list[str]:
        """Read the ``tags`` filter from the project config's job entry."""
        config_path = _REPO_ROOT / "teleclaude.yml"
        project_config = load_project_config(config_path)
        job_config = project_config.jobs.get(self.name)
        if job_config is None:
            return []
        return list(getattr(job_config, "tags", []) or [])

    async def _scrape_subscriber(
        self,
        subscriber: Subscriber,
        job_tags: list[str],
    ) -> tuple[int, int, list[str]]:
        """Scrape matching channels for one subscriber.

        Returns ``(channels_evaluated, videos_found, errors)``.
        """
        csv_path = subscriber.subscriptions_dir / "youtube.csv"
        rows = read_csv(csv_path)
        matching = filter_channels_by_tags(rows, job_tags)

        scope_label = subscriber.name or "global"
        logger.info(
            "subscriber channels",
            scope=scope_label,
            total=len(rows),
            matching=len(matching),
        )

        videos_found = 0
        errors: list[str] = []

        for row in matching:
            try:
                videos: list[Video] = await youtube_search(
                    channels=row.handle or row.channel_name,
                    query=row.channel_name,
                    period_days=self.period_days,
                    get_transcripts=False,
                )
                videos_found += len(videos)
                logger.info(
                    "channel scraped",
                    scope=scope_label,
                    channel=row.channel_name,
                    videos=len(videos),
                )
            except Exception as e:
                errors.append(f"{scope_label}/{row.channel_name}: {e}")
                logger.warning("scrape failed", scope=scope_label, channel=row.channel_name, error=str(e))

        return len(matching), videos_found, errors

    async def _run_async(self) -> JobResult:
        """Async implementation of the scraping pipeline."""
        job_tags = self._job_tags()

        if not job_tags:
            return JobResult(
                success=True,
                message="No tags configured — nothing to scrape",
                items_processed=0,
            )

        subscribers = discover_youtube_subscribers()

        if not subscribers:
            return JobResult(
                success=True,
                message="No YouTube subscribers configured",
                items_processed=0,
            )

        total_channels = 0
        total_videos = 0
        all_errors: list[str] = []

        for subscriber in subscribers:
            channels_evaluated, videos_found, errors = await self._scrape_subscriber(subscriber, job_tags)
            total_channels += channels_evaluated
            total_videos += videos_found
            all_errors.extend(errors)

        success = len(all_errors) == 0
        message = (
            f"Scraped {total_channels} channel(s), found {total_videos} video(s)"
            if success
            else f"Completed with {len(all_errors)} error(s); {total_channels} channel(s) evaluated, {total_videos} video(s) found"
        )

        return JobResult(
            success=success,
            message=message,
            items_processed=total_videos,
            errors=all_errors if all_errors else None,
        )

    def run(self) -> JobResult:
        """Execute channel scraping for all subscribers."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._run_async())
        finally:
            loop.close()


# Job instance for discovery by runner
JOB = YouTubeScraperJob()

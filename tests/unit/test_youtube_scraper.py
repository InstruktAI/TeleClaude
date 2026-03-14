"""Unit tests for YouTubeScraperJob.

Tests:
1. filter_channels_by_tags — tag intersection logic and edge cases.
2. Job result reporting — correct counts in JobResult.items_processed.
3. Config access — tags read from JobScheduleConfig with extra="allow".
4. Runner schedule contract — both jobs are category: system.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from jobs.youtube_scraper import YouTubeScraperJob, filter_channels_by_tags
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.tagging.youtube import ChannelRow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(channel_name: str, tags: str, handle: str = "") -> ChannelRow:
    return ChannelRow(channel_id=f"id-{channel_name}", channel_name=channel_name, handle=handle, tags=tags)


# ---------------------------------------------------------------------------
# 1. filter_channels_by_tags
# ---------------------------------------------------------------------------


class TestFilterChannelsByTags:
    def test_matching_tag_selected(self):
        rows = [_row("TechChan", "ai,devtools")]
        assert filter_channels_by_tags(rows, ["ai"]) == rows

    def test_no_match_excluded(self):
        rows = [_row("GameChan", "gaming")]
        assert filter_channels_by_tags(rows, ["ai"]) == []

    def test_empty_job_tags_returns_nothing(self):
        rows = [_row("TechChan", "ai")]
        assert filter_channels_by_tags(rows, []) == []

    def test_channel_with_empty_tags_excluded(self):
        rows = [_row("EmptyChan", "")]
        assert filter_channels_by_tags(rows, ["ai"]) == []

    def test_channel_with_na_tags_excluded(self):
        rows = [_row("NaChan", "n/a")]
        assert filter_channels_by_tags(rows, ["ai"]) == []

    def test_partial_overlap_included(self):
        rows = [_row("MixedChan", "ai,gaming")]
        assert filter_channels_by_tags(rows, ["ai"]) == rows

    def test_multiple_rows_filtered_correctly(self):
        rows = [
            _row("TechChan", "ai,devtools"),
            _row("GameChan", "gaming"),
            _row("NaChan", "n/a"),
            _row("EmptyChan", ""),
            _row("MixedChan", "ai,gaming"),
        ]
        result = filter_channels_by_tags(rows, ["ai"])
        assert [r.channel_name for r in result] == ["TechChan", "MixedChan"]

    def test_na_mixed_with_real_tags_real_tags_match(self):
        # "n/a" tokens inside a multi-tag string are stripped; real tags still match.
        rows = [_row("Weird", "n/a,ai")]
        assert filter_channels_by_tags(rows, ["ai"]) == rows


# ---------------------------------------------------------------------------
# 2. Job result reporting
# ---------------------------------------------------------------------------


class TestJobResultReporting:
    def _make_subscriber(self, name: str) -> MagicMock:
        sub = MagicMock()
        sub.name = name
        sub.subscriptions_dir = Path("/fake") / name / "subscriptions"
        return sub

    def _make_video(self) -> MagicMock:
        v = MagicMock()
        return v

    def test_items_processed_counts_videos(self):
        rows = [_row("TechChan", "ai", handle="@techchan")]
        subscriber = self._make_subscriber("alice")
        videos = [self._make_video(), self._make_video()]

        job = YouTubeScraperJob()

        with (
            patch.object(job, "_job_tags", return_value=["ai"]),
            patch("jobs.youtube_scraper.discover_youtube_subscribers", return_value=[subscriber]),
            patch("jobs.youtube_scraper.read_csv", return_value=rows),
            patch("jobs.youtube_scraper.youtube_search", new_callable=AsyncMock, return_value=videos),
        ):
            result = job.run()

        assert result.success is True
        assert result.items_processed == 2

    def test_no_subscribers_returns_zero(self):
        job = YouTubeScraperJob()

        with (
            patch.object(job, "_job_tags", return_value=["ai"]),
            patch("jobs.youtube_scraper.discover_youtube_subscribers", return_value=[]),
        ):
            result = job.run()

        assert result.success is True
        assert result.items_processed == 0

    def test_no_job_tags_returns_zero(self):
        job = YouTubeScraperJob()

        with patch.object(job, "_job_tags", return_value=[]):
            result = job.run()

        assert result.success is True
        assert result.items_processed == 0

    def test_scrape_error_recorded_in_result(self):
        rows = [_row("TechChan", "ai", handle="@techchan")]
        subscriber = self._make_subscriber("alice")

        job = YouTubeScraperJob()

        with (
            patch.object(job, "_job_tags", return_value=["ai"]),
            patch("jobs.youtube_scraper.discover_youtube_subscribers", return_value=[subscriber]),
            patch("jobs.youtube_scraper.read_csv", return_value=rows),
            patch(
                "jobs.youtube_scraper.youtube_search", new_callable=AsyncMock, side_effect=RuntimeError("network error")
            ),
        ):
            result = job.run()

        assert result.success is False
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "network error" in result.errors[0]

    def test_multiple_subscribers_counts_aggregated(self):
        rows = [_row("TechChan", "ai", handle="@techchan")]
        sub_a = self._make_subscriber("alice")
        sub_b = self._make_subscriber("bob")
        videos = [self._make_video()]

        job = YouTubeScraperJob()

        with (
            patch.object(job, "_job_tags", return_value=["ai"]),
            patch("jobs.youtube_scraper.discover_youtube_subscribers", return_value=[sub_a, sub_b]),
            patch("jobs.youtube_scraper.read_csv", return_value=rows),
            patch("jobs.youtube_scraper.youtube_search", new_callable=AsyncMock, return_value=videos),
        ):
            result = job.run()

        # One video per subscriber * 2 subscribers
        assert result.items_processed == 2


# ---------------------------------------------------------------------------
# 3. Config access — extra="allow" mechanism
# ---------------------------------------------------------------------------


class TestConfigAccess:
    def test_tags_readable_from_extra_field(self):
        config = JobScheduleConfig.model_validate(
            {
                "category": "system",
                "when": {"at": "06:00"},
                "script": "jobs/youtube_scraper.py",
                "tags": ["ai", "devtools"],
            }
        )
        assert getattr(config, "tags", None) == ["ai", "devtools"]

    def test_missing_tags_returns_empty(self):
        config = JobScheduleConfig.model_validate({"category": "system"})
        assert getattr(config, "tags", []) == []


# ---------------------------------------------------------------------------
# 4. Runner schedule contract — both jobs are category: system
# ---------------------------------------------------------------------------


class TestRunnerScheduleContract:
    def test_both_jobs_are_system_category(self):
        config_path = Path(__file__).resolve().parents[2] / "teleclaude.yml"
        from teleclaude.config.loader import load_project_config

        project_config = load_project_config(config_path)

        scraper = project_config.jobs.get("youtube_scraper")
        assert scraper is not None, "youtube_scraper entry missing from teleclaude.yml"
        assert scraper.category == "system", f"youtube_scraper.category={scraper.category!r}, expected 'system'"

        sync = project_config.jobs.get("youtube_sync_subscriptions")
        assert sync is not None, "youtube_sync_subscriptions entry missing from teleclaude.yml"
        assert sync.category == "system", f"youtube_sync_subscriptions.category={sync.category!r}, expected 'system'"

    def test_scraper_points_to_correct_script(self):
        config_path = Path(__file__).resolve().parents[2] / "teleclaude.yml"
        from teleclaude.config.loader import load_project_config

        project_config = load_project_config(config_path)
        scraper = project_config.jobs["youtube_scraper"]
        assert scraper.script == "jobs/youtube_scraper.py"

    def test_sync_points_to_correct_script(self):
        config_path = Path(__file__).resolve().parents[2] / "teleclaude.yml"
        from teleclaude.config.loader import load_project_config

        project_config = load_project_config(config_path)
        sync = project_config.jobs["youtube_sync_subscriptions"]
        assert sync.script == "jobs/youtube_sync_subscriptions.py"

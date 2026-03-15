"""Characterization tests for teleclaude.tagging.youtube."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cron.discovery import Subscriber
from teleclaude.tagging import youtube

pytestmark = pytest.mark.unit


class TestChannelRow:
    def test_round_trips_to_and_from_csv_dict(self) -> None:
        row = youtube.ChannelRow(channel_id="abc", channel_name="Channel", handle="@channel", tags="ai")

        assert youtube.ChannelRow.from_dict(row.to_dict()) == row


class TestCleanupStaleTags:
    def test_rewrites_removed_tags_to_remaining_values(self) -> None:
        rows = [youtube.ChannelRow(channel_id="1", channel_name="Channel", tags="ai,old")]

        modified = youtube.cleanup_stale_tags(rows, {"ai"})

        assert modified == 1
        assert rows[0].tags == "ai"


class TestBuildBatchPrompt:
    def test_includes_description_in_normal_mode_and_omits_it_in_web_mode(self) -> None:
        rows = [youtube.ChannelRow(channel_id="1", channel_name="Channel", handle="@channel", description="About")]

        normal_prompt = youtube.build_batch_prompt(rows, ["ai"], use_web=False)
        web_prompt = youtube.build_batch_prompt(rows, ["ai"], use_web=True)

        assert '"description": "About"' in normal_prompt
        assert '"description": ""' in web_prompt
        assert "Search for each YouTube channel" in web_prompt


class TestValidateTags:
    def test_rejects_na_combined_with_real_tags_and_requires_evidence(self) -> None:
        assert youtube.validate_tags(["n/a", "ai"], {"ai"}, "reason") is None
        assert youtube.validate_tags(["ai"], {"ai"}, "") is None
        assert youtube.validate_tags(["ai"], {"ai"}, "known creator") == ["ai"]


class TestProcessBatch:
    def test_returns_updates_from_agent_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [
            youtube.ChannelRow(channel_id="1", channel_name="One"),
            youtube.ChannelRow(channel_id="2", channel_name="Two"),
        ]
        config = youtube.TaggingConfig(prompt_batch=2, agents=["claude"])
        monkeypatch.setattr(
            youtube,
            "call_agent",
            lambda agent, thinking_mode, prompt, schema, use_web=False: {
                "items": [
                    {"channel_id": "1", "tags": ["ai"], "evidence": "known"},
                    {"channel_id": "2", "tags": ["n/a"], "evidence": "n/a"},
                ]
            },
        )

        updates = youtube.process_batch(
            rows,
            config,
            tags=["ai"],
            allowed_tags={"ai"},
            agent_iter=youtube.round_robin(["claude"]),
        )

        assert updates == {"1": "ai", "2": "n/a"}


class TestApplyUpdates:
    def test_merge_mode_unions_existing_and_new_tags(self) -> None:
        rows = [youtube.ChannelRow(channel_id="1", channel_name="One", tags="ai")]

        youtube.apply_updates(rows, {"1": "tools,ai"}, merge_mode=True)

        assert rows[0].tags == "ai,tools"


class TestSyncYoutubeSubscriptions:
    def test_returns_error_when_subscriber_has_no_tags(self, tmp_path: Path) -> None:
        subscriber = Subscriber(
            scope="person",
            name="morris",
            config_path=tmp_path / "teleclaude.yml",
            tags=[],
        )

        result = youtube.sync_youtube_subscriptions(subscriber)

        assert result.errors == ["No tags configured"]

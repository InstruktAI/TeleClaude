"""Characterization tests for teleclaude.helpers.youtube_helper._models."""

from __future__ import annotations

import pytest

from teleclaude.helpers.youtube_helper import _models

pytestmark = pytest.mark.unit


class TestVideoModel:
    def test_video_keeps_optional_description_and_transcript(self) -> None:
        video = _models.Video(
            id="vid-1",
            title="Demo",
            short_desc="Short",
            channel="Channel",
            duration="10:00",
            views="100 views",
            publish_time="1 day ago",
            url_suffix="/watch?v=vid-1",
            long_desc="Longer text",
            transcript="Transcript body",
        )

        assert video.long_desc == "Longer text"
        assert video.transcript == "Transcript body"


class TestSubscriptionChannel:
    def test_optional_fields_default_to_none(self) -> None:
        channel = _models.SubscriptionChannel(id="abc", title="Channel")

        assert channel.handle is None
        assert channel.url_suffix is None
        assert channel.description is None
        assert channel.subscribers is None


class TestBackoffError:
    def test_backoff_error_is_runtime_error(self) -> None:
        error = _models.YouTubeBackoffError("slow down")

        assert isinstance(error, RuntimeError)

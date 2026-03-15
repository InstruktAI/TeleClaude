"""Characterization tests for teleclaude.hooks.checkpoint._models."""

from __future__ import annotations

import pytest

from teleclaude.hooks.checkpoint._models import CheckpointContext, CheckpointResult, TranscriptObservability


class TestCheckpointContext:
    @pytest.mark.unit
    def test_context_preserves_agent_name_and_optional_slug(self) -> None:
        context = CheckpointContext(agent_name="claude", project_path="/repo", working_slug="chartest-hooks")

        assert context.agent_name == "claude"
        assert context.project_path == "/repo"
        assert context.working_slug == "chartest-hooks"


class TestCheckpointResult:
    @pytest.mark.unit
    def test_result_defaults_to_empty_lists_and_false_all_clear(self) -> None:
        result = CheckpointResult()

        assert result.categories == []
        assert result.required_actions == []
        assert result.observations == []
        assert result.is_all_clear is False


class TestTranscriptObservability:
    @pytest.mark.unit
    def test_typed_dict_shape_accepts_transcript_observability_fields(self) -> None:
        observability: TranscriptObservability = {
            "transcript_path": "/tmp/session.jsonl",
            "transcript_exists": True,
            "transcript_size_bytes": 42,
        }

        assert observability["transcript_exists"] is True
        assert observability["transcript_size_bytes"] == 42

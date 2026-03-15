"""Characterization tests for teleclaude.hooks.normalizers.github."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.hooks.normalizers.github import normalize_github


class TestNormalizeGithub:
    @pytest.mark.unit
    def test_normalizes_standard_event_headers_and_selected_payload_fields(self) -> None:
        event = normalize_github(
            {
                "action": "opened",
                "ref": "refs/heads/main",
                "repository": {"full_name": "owner/repo"},
                "sender": {"login": "alice"},
            },
            {"X-GitHub-Event": "pull_request"},
        )

        assert event.source == "github"
        assert event.type == "pull_request"
        assert event.properties == {
            "repo": "owner/repo",
            "sender": "alice",
            "action": "opened",
            "ref": "refs/heads/main",
        }
        assert datetime.fromisoformat(event.timestamp).tzinfo == UTC

    @pytest.mark.unit
    def test_ping_events_include_optional_zen_and_string_hook_id(self) -> None:
        event = normalize_github(
            {
                "zen": "Keep it logically awesome.",
                "hook_id": "7",
            },
            {"x-github-event": "ping"},
        )

        assert event.type == "ping"
        assert event.properties == {
            "repo": None,
            "sender": None,
            "action": None,
            "ref": None,
            "zen": "Keep it logically awesome.",
            "hook_id": "7",
        }

    @pytest.mark.unit
    def test_missing_event_header_falls_back_to_unknown(self) -> None:
        event = normalize_github({}, {})

        assert event.type == "unknown"

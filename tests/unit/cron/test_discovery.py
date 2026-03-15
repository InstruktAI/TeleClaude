"""Characterization tests for teleclaude.cron.discovery."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from teleclaude.cron.discovery import discover_youtube_subscribers


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class TestDiscoverYoutubeSubscribers:
    @pytest.mark.unit
    def test_returns_global_and_person_subscribers_with_tags(self, tmp_path: Path) -> None:
        root = tmp_path / ".teleclaude"
        _write_yaml(
            root / "teleclaude.yml",
            """
            subscriptions:
              - type: youtube
                source: "@teleclaude"
              - type: youtube
                source: "@ignored"
                enabled: false
            interests:
              tags:
                - ai
                - releases
            """,
        )
        _write_yaml(
            root / "people" / "alice" / "teleclaude.yml",
            """
            creds:
              telegram:
                user_name: alice
                user_id: 101
            subscriptions:
              - type: youtube
                source: "@alice"
            interests:
              - devtools
            """,
        )
        _write_yaml(
            root / "people" / "bob" / "teleclaude.yml",
            """
            subscriptions:
              - type: job
                job: digest
                when:
                  at: "09:00"
            """,
        )

        subscribers = discover_youtube_subscribers(root)

        assert [(subscriber.scope, subscriber.name, subscriber.tags) for subscriber in subscribers] == [
            ("global", None, ["ai", "releases"]),
            ("person", "alice", ["devtools"]),
        ]
        assert subscribers[1].subscriptions_dir == root / "people" / "alice" / "subscriptions"

    @pytest.mark.unit
    def test_ignores_disabled_and_non_youtube_subscriptions(self, tmp_path: Path) -> None:
        root = tmp_path / ".teleclaude"
        _write_yaml(
            root / "teleclaude.yml",
            """
            subscriptions:
              - type: youtube
                source: "@teleclaude"
                enabled: false
            """,
        )
        (root / "people").mkdir(parents=True, exist_ok=True)
        (root / "people" / "notes.txt").write_text("not a person directory\n", encoding="utf-8")
        _write_yaml(
            root / "people" / "charlie" / "teleclaude.yml",
            """
            subscriptions:
              - type: youtube
                source: "@charlie"
                enabled: false
            """,
        )
        _write_yaml(
            root / "people" / "dana" / "teleclaude.yml",
            """
            subscriptions:
              - type: job
                job: digest
                when:
                  at: "09:00"
            """,
        )

        assert discover_youtube_subscribers(root) == []

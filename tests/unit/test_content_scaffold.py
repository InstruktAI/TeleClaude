"""Characterization tests for teleclaude.content_scaffold."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

import teleclaude.content_scaffold as content_scaffold


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> FrozenDateTime:
        return cls(2025, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_derive_slug_drops_short_words_and_limits_to_five_words() -> None:
    slug = content_scaffold._derive_slug("A I build the future of AI, now, together.")
    assert slug == "build-the-future-of-ai"


def test_create_content_inbox_entry_writes_content_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(content_scaffold, "datetime", FrozenDateTime)

    entry_dir = content_scaffold.create_content_inbox_entry(
        tmp_path,
        "Hello world from the scaffold",
        tags=["note"],
        author="me@example.com",
    )

    assert entry_dir == tmp_path / "publications" / "inbox" / "20250102-hello-world-from-the-scaffold"
    assert (entry_dir / "content.md").read_text(encoding="utf-8") == "Hello world from the scaffold"
    assert yaml.safe_load((entry_dir / "meta.yaml").read_text(encoding="utf-8")) == {
        "author": "me@example.com",
        "tags": ["note"],
        "created_at": "2025-01-02T03:04:05+00:00",
    }


def test_create_content_inbox_entry_uses_unique_slug_suffix_when_folder_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(content_scaffold, "datetime", FrozenDateTime)

    existing_dir = tmp_path / "publications" / "inbox" / "20250102-idea"
    existing_dir.mkdir(parents=True)

    entry_dir = content_scaffold.create_content_inbox_entry(
        tmp_path,
        "Different content",
        slug="idea",
        author="me@example.com",
    )

    assert entry_dir.name == "20250102-idea-2"

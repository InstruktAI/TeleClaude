"""Characterization tests for teleclaude.entrypoints.youtube_sync_subscriptions."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import teleclaude.entrypoints.youtube_sync_subscriptions as youtube_sync_subscriptions


def test_validate_tags_requires_evidence_and_rejects_mixed_na() -> None:
    allowed = {"tech", "music"}

    assert youtube_sync_subscriptions._validate_tags(["tech"], allowed, "known creator") == ["tech"]
    assert youtube_sync_subscriptions._validate_tags(["tech"], allowed, None) is None
    assert youtube_sync_subscriptions._validate_tags(["n/a", "tech"], allowed, "mixed") is None
    assert youtube_sync_subscriptions._validate_tags(["n/a"], allowed, "n/a") == ["n/a"]


def test_fetch_new_rows_skips_seen_channels_and_applies_max_new(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(fetch_subscriptions=True, debug=False, max_new=1)
    monkeypatch.setattr(
        youtube_sync_subscriptions,
        "_call_youtube_helper",
        lambda: [
            {"id": "seen-1", "title": "Seen", "handle": "@seen", "description": "skip"},
            {"id": "new-1", "title": "First", "handle": "@first", "description": "desc-1"},
            {"id": "new-2", "title": "Second", "handle": None, "description": None},
        ],
    )

    rows = youtube_sync_subscriptions._fetch_new_rows(args, {"seen-1"})

    assert rows == [
        {
            "channel_id": "new-1",
            "channel_name": "First",
            "handle": "@first",
            "tags": "",
            "_description": "desc-1",
        }
    ]


def test_apply_batch_updates_merges_existing_tags_and_persists_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "youtube.csv"
    args = argparse.Namespace(dry_run=False)
    all_rows = [
        {
            "channel_id": "channel-1",
            "channel_name": "Channel One",
            "handle": "@one",
            "tags": "history,n/a",
        },
        {
            "channel_id": "channel-2",
            "channel_name": "Channel Two",
            "handle": "@two",
            "tags": "",
        },
    ]

    youtube_sync_subscriptions._apply_batch_updates(
        args=args,
        csv_path=csv_path,
        all_rows=all_rows,
        batch_updates={"channel-1": "music,history", "channel-2": "n/a"},
        merge_mode=True,
    )

    persisted = youtube_sync_subscriptions._read_csv(csv_path)

    assert all_rows[0]["tags"] == "history,music"
    assert all_rows[1]["tags"] == "n/a"
    assert persisted == all_rows

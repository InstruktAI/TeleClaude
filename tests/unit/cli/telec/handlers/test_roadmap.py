from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

roadmap = importlib.import_module("teleclaude.cli.telec.handlers.roadmap")


def test_parse_roadmap_show_args_sets_requested_flags() -> None:
    parsed = roadmap._parse_roadmap_show_args(["--include-icebox", "--delivered-only", "--json"])

    assert parsed == {
        "include_icebox": True,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": True,
        "json_output": True,
    }


def test_handle_roadmap_show_prints_json_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    todos = [
        SimpleNamespace(
            slug="sample",
            status="ready",
            description=None,
            after=[],
            group=None,
            delivered_at=None,
        )
    ]

    monkeypatch.chdir(tmp_path)
    with patch("teleclaude.core.roadmap.assemble_roadmap_from_db", return_value=todos):
        roadmap._handle_roadmap_show(["--json"])

    assert json.loads(capsys.readouterr().out) == [{"slug": "sample", "status": "ready"}]


def test_handle_roadmap_add_forwards_parsed_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_called: list[tuple[str, str]] = []
    monkeypatch.chdir(tmp_path)
    with patch(
        "teleclaude.cli.telec.handlers.roadmap._run_db",
        side_effect=lambda slug, method, **kw: (db_called.append((slug, method)) or True),
    ):
        roadmap._handle_roadmap_add(
            ["sample", "--group", "core", "--after", "dep-a,dep-b", "--description", "Demo", "--before", "other"]
        )

    assert db_called[0] == ("sample", "add_to_roadmap")


def test_handle_roadmap_deliver_calls_db_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_called: list[tuple[str, str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        roadmap,
        "_run_db",
        lambda slug, method, **kw: (db_called.append((slug, method)) or True),
    )

    with patch("teleclaude.core.next_machine.core.cleanup_delivered_slug"):
        roadmap._handle_roadmap_deliver(["sample", "--commit", "abc123"])

    assert db_called[0] == ("sample", "deliver")

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

content = importlib.import_module("teleclaude.cli.telec.handlers.content")


def test_handle_content_dispatches_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(content, "_handle_content_dump", lambda args: received.append(args))

    content._handle_content(["dump", "brain dump"])

    assert received == [["brain dump"]]


def test_handle_content_dump_creates_entry_and_emits_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry_dir = tmp_path / "content" / "entry-1"
    logger = MagicMock()
    emitted_timeouts: list[float] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(content, "_resolve_author", lambda: "author@example.com")
    monkeypatch.setattr(content, "normalize_slug", lambda _slug: "normalized")
    monkeypatch.setattr(content, "create_content_inbox_entry", lambda *args, **kwargs: entry_dir)
    monkeypatch.setattr(
        content, "tool_api_request", lambda _method, _path, **kwargs: emitted_timeouts.append(kwargs["timeout"])
    )
    monkeypatch.setattr(content, "get_logger", lambda _name: logger)

    content._handle_content_dump(["Some text", "--slug", "Custom Slug", "--tags", "a,b"])

    assert emitted_timeouts == [5.0]
    logger.info.assert_called_once()


def test_handle_content_dump_rejects_second_text_argument(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(content, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        content._handle_content_dump(["one", "two"])

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.strip()


def test_handle_content_dump_survives_event_emit_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry_dir = tmp_path / "content" / "entry-1"
    logger = MagicMock()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(content, "_resolve_author", lambda: "author@example.com")
    monkeypatch.setattr(content, "create_content_inbox_entry", lambda *args, **kwargs: entry_dir)
    monkeypatch.setattr(
        content, "tool_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(content, "get_logger", lambda _name: logger)

    content._handle_content_dump(["Some text"])

    logger.info.assert_called_once()

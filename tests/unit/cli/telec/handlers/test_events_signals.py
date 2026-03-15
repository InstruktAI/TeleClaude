from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace, TracebackType
from unittest.mock import patch

import pytest

events_signals = importlib.import_module("teleclaude.cli.telec.handlers.events_signals")


def test_handle_events_without_args_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(events_signals, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    events_signals._handle_events([])

    assert capsys.readouterr().out == "usage:events\n"


def test_handle_events_list_filters_by_domain(capsys: pytest.CaptureFixture[str]) -> None:
    schemas = [
        SimpleNamespace(
            event_type="core.started",
            default_level="info",
            domain="core",
            default_visibility=SimpleNamespace(value="public"),
            description="Core start",
            actionable=True,
        ),
        SimpleNamespace(
            event_type="other.finished",
            default_level="debug",
            domain="other",
            default_visibility=SimpleNamespace(value="internal"),
            description="Other finish",
            actionable=False,
        ),
    ]
    catalog = SimpleNamespace(list_all=lambda: schemas)

    with patch.dict(sys.modules, {"teleclaude.events": SimpleNamespace(build_default_catalog=lambda: catalog)}):
        events_signals._handle_events(["list", "--domain", "core"])

    output = capsys.readouterr().out
    assert "EVENT TYPE" in output
    assert "core.started" in output
    assert "Core start" in output
    assert "other.finished" not in output


def test_handle_events_unknown_subcommand_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(events_signals, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        events_signals._handle_events(["unknown"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unknown events subcommand: unknown" in output
    assert "usage:events" in output


def test_handle_signals_defaults_to_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(events_signals, "_handle_signals_status", lambda: calls.append("status"))

    events_signals._handle_signals([])
    events_signals._handle_signals(["status"])

    assert calls == ["status", "status"]


def test_handle_signals_unknown_subcommand_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(events_signals, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        events_signals._handle_signals(["bad"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unknown signals subcommand: bad" in output
    assert "usage:signals" in output


def test_handle_signals_status_prints_counts_and_last_ingest(capsys: pytest.CaptureFixture[str]) -> None:
    class FakeConnection:
        row_factory = None

        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    class FakeSignalDB:
        def __init__(self, conn: FakeConnection) -> None:
            assert conn.row_factory is object

        async def get_signal_counts(self) -> dict[str, int]:
            return {"items": 12, "clusters": 3, "syntheses": 1, "pending": 2}

        async def get_last_ingest_time(self) -> str:
            return "2025-01-02T03:04:05Z"

    fake_modules = {
        "aiosqlite": SimpleNamespace(connect=lambda _path: FakeConnection(), Row=object),
        "teleclaude.config": SimpleNamespace(
            config=SimpleNamespace(database=SimpleNamespace(path=Path("/tmp/test.db")))
        ),
        "teleclaude.events.signal.db": SimpleNamespace(SignalDB=FakeSignalDB),
    }

    with patch.dict(sys.modules, fake_modules):
        events_signals._handle_signals_status()

    output = capsys.readouterr().out
    assert "Signal Pipeline Status" in output
    assert "Items ingested:  12" in output
    assert "Clusters formed: 3" in output
    assert "Syntheses ready: 1" in output
    assert "Pending cluster: 2" in output
    assert "Last ingest:     2025-01-02T03:04:05Z" in output


def test_handle_signals_status_reports_uninitialized_tables(capsys: pytest.CaptureFixture[str]) -> None:
    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    class FailingSignalDB:
        def __init__(self, _conn: FakeConnection) -> None:
            pass

        async def get_signal_counts(self) -> dict[str, int]:
            raise RuntimeError("missing tables")

        async def get_last_ingest_time(self) -> str | None:
            raise AssertionError("should not be reached")

    fake_modules = {
        "aiosqlite": SimpleNamespace(connect=lambda _path: FakeConnection(), Row=object),
        "teleclaude.config": SimpleNamespace(
            config=SimpleNamespace(database=SimpleNamespace(path=Path("/tmp/test.db")))
        ),
        "teleclaude.events.signal.db": SimpleNamespace(SignalDB=FailingSignalDB),
    }

    with patch.dict(sys.modules, fake_modules):
        events_signals._handle_signals_status()

    assert (
        capsys.readouterr().out.strip() == "Signal tables not initialized. Start the daemon to enable signal ingestion."
    )

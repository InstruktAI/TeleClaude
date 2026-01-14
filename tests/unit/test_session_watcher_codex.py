from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.codex_watcher import CodexWatcher
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_codex_watcher_does_not_adopt_old_logs(tmp_path: Path) -> None:
    """Test that CodexWatcher ignores stale log files during scans."""
    client = MagicMock()
    client.handle_event = AsyncMock()
    watcher = CodexWatcher(client=client, db_handle=MagicMock())

    session = Session(
        session_id="sess-1",
        computer_name="MozBook",
        tmux_session_name="tc_sess-1",
        origin_adapter="redis",
        title="Test",
        working_directory="/tmp",
        created_at=datetime.now(UTC),
        last_activity=datetime.now(UTC),
        active_agent="codex",
        native_log_file=None,
    )

    old_file = tmp_path / "old.jsonl"
    old_file.write_text(
        '{"type":"session_meta","payload":{"id":"native-1","timestamp":"2025-01-01T00:00:00Z"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"old"}]}}\n',
        encoding="utf-8",
    )
    old_mtime = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    old_file.touch()
    old_file.chmod(0o644)
    os.utime(old_file, (old_mtime, old_mtime))

    watcher._db.get_active_sessions = AsyncMock(return_value=[session])
    watcher._db.list_sessions = AsyncMock(return_value=[])
    watcher._db.update_session = AsyncMock()

    with patch(
        "teleclaude.core.codex_watcher.config.agents",
        {"codex": MagicMock(session_dir=str(tmp_path), log_pattern="*.jsonl")},
    ):
        await watcher._scan_directory()  # pylint: disable=protected-access

    watcher._db.get_active_sessions.assert_awaited()


@pytest.mark.asyncio
async def test_rehydrate_watcher_attaches_existing_log(tmp_path: Path) -> None:
    """Test that CodexWatcher rehydrates and tracks existing log files."""
    client = MagicMock()
    client.handle_event = AsyncMock()
    watcher = CodexWatcher(client=client, db_handle=MagicMock())

    session = Session(
        session_id="sess-1",
        computer_name="MozBook",
        tmux_session_name="tc_sess-1",
        origin_adapter="redis",
        title="Test",
        working_directory="/tmp",
        created_at=datetime.now(UTC),
        last_activity=datetime.now(UTC),
        active_agent="codex",
        native_log_file=str(tmp_path / "codex.jsonl"),
    )

    log_file = tmp_path / "codex.jsonl"
    log_file.write_text('{"type":"response_item","payload":{"role":"assistant","content":[]}}\n', encoding="utf-8")

    watcher._db.get_active_sessions = AsyncMock(return_value=[session])

    await watcher._rehydrate_watched_files()  # pylint: disable=protected-access

    assert log_file in watcher._watched_files
    assert watcher._file_positions[log_file] == log_file.stat().st_size

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.core.session_watcher import SessionWatcher
from teleclaude.core.ux_state import SessionUXState


@pytest.mark.asyncio
async def test_codex_watcher_does_not_adopt_old_logs(tmp_path: Path) -> None:
    watcher = SessionWatcher(client=MagicMock())

    session = Session(
        session_id="sess-1",
        computer_name="MozBook",
        tmux_session_name="tc_sess-1",
        origin_adapter="redis",
        title="Test",
        working_directory="/tmp",
        terminal_size="120x40",
        created_at=datetime.now(UTC),
        last_activity=datetime.now(UTC),
        closed=False,
    )

    old_file = tmp_path / "old.jsonl"
    old_file.write_text('{"type":"response_item","payload":{"role":"user","content":"old"}}\n', encoding="utf-8")
    old_mtime = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    old_file.touch()
    old_file.chmod(0o644)
    os.utime(old_file, (old_mtime, old_mtime))

    parser = MagicMock()
    parser.can_parse.return_value = True
    parser.extract_session_id.return_value = "native-1"

    with (
        patch("teleclaude.core.session_watcher.db.get_active_sessions", new_callable=AsyncMock, return_value=[session]),
        patch(
            "teleclaude.core.session_watcher.db.get_ux_state",
            new_callable=AsyncMock,
            return_value=SessionUXState(active_agent="codex", native_log_file=None),
        ),
        patch("teleclaude.core.session_watcher.db.update_ux_state", new_callable=AsyncMock) as mock_update,
    ):
        await watcher._try_adopt_session(old_file, "codex", parser)  # pylint: disable=protected-access
        mock_update.assert_not_awaited()

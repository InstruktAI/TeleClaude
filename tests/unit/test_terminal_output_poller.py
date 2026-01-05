"""Unit tests for TerminalOutputPoller."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from teleclaude.core.terminal_output_poller import TerminalOutputPoller


@pytest.mark.asyncio
async def test_terminal_output_poller_emits_screen_changes(tmp_path: Path) -> None:
    log_file = tmp_path / "tui.log"
    log_file.write_text("", encoding="utf-8")

    poller = TerminalOutputPoller(poll_interval=0.01)

    async def _emit() -> None:
        await asyncio.sleep(0.05)
        log_file.write_text("\x1b[2JHello", encoding="utf-8")

    asyncio.create_task(_emit())

    event = await asyncio.wait_for(
        anext(poller.poll("sess-1", log_file, "80x24", pid=None)),
        timeout=1.0,
    )

    assert "Hello" in event.output

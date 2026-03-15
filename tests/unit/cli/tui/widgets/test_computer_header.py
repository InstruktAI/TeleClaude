"""Characterization tests for teleclaude.cli.tui.widgets.computer_header."""

from __future__ import annotations

import pytest

from teleclaude.cli.models import ComputerInfo
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader


def _make_data(*, name: str = "local", status: str = "online", session_count: int = 0) -> ComputerDisplayInfo:
    computer = ComputerInfo(name=name, status=status, is_local=True)
    return ComputerDisplayInfo(computer=computer, session_count=session_count, recent_activity=False)


@pytest.mark.unit
def test_computer_header_is_importable() -> None:
    assert ComputerHeader is not None


@pytest.mark.unit
def test_computer_header_stores_data() -> None:
    data = _make_data(name="my-computer")
    header = ComputerHeader(data=data)
    assert header.data is data


@pytest.mark.unit
def test_computer_header_pressed_message_is_defined() -> None:
    assert ComputerHeader.Pressed is not None

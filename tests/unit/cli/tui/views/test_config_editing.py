"""Characterization tests for teleclaude.cli.tui.views.config_editing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.views.config_editing import ConfigContentEditingMixin


def _make_editing_host(*, editing: bool = True) -> ConfigContentEditingMixin:
    """Build a minimal fake host satisfying editing mixin attr requirements."""
    obj = ConfigContentEditingMixin()
    obj.is_editing = editing
    obj._edit_buffer = ""
    obj._editing_var_name = "FAKE_VAR" if editing else None
    obj._editing_person_field = None
    obj.refresh = MagicMock()
    return obj


@pytest.mark.unit
def test_append_edit_character_appends_char_to_buffer() -> None:
    host = _make_editing_host(editing=True)
    host.append_edit_character("a")
    assert host._edit_buffer == "a"


@pytest.mark.unit
def test_append_edit_character_accumulates_multiple_chars() -> None:
    host = _make_editing_host(editing=True)
    host.append_edit_character("h")
    host.append_edit_character("i")
    assert host._edit_buffer == "hi"


@pytest.mark.unit
def test_append_edit_character_does_nothing_when_not_editing() -> None:
    host = _make_editing_host(editing=False)
    host.append_edit_character("x")
    assert host._edit_buffer == ""


@pytest.mark.unit
def test_backspace_edit_removes_last_character() -> None:
    host = _make_editing_host(editing=True)
    host._edit_buffer = "abc"
    host.backspace_edit()
    assert host._edit_buffer == "ab"


@pytest.mark.unit
def test_backspace_edit_on_empty_buffer_stays_empty() -> None:
    host = _make_editing_host(editing=True)
    host.backspace_edit()
    assert host._edit_buffer == ""


@pytest.mark.unit
def test_backspace_edit_does_nothing_when_not_editing() -> None:
    host = _make_editing_host(editing=False)
    host._edit_buffer = "xyz"
    host.backspace_edit()
    assert host._edit_buffer == "xyz"


@pytest.mark.unit
def test_clear_edit_buffer_empties_buffer() -> None:
    host = _make_editing_host(editing=True)
    host._edit_buffer = "hello"
    host.clear_edit_buffer()
    assert host._edit_buffer == ""


@pytest.mark.unit
def test_clear_edit_buffer_does_nothing_when_not_editing() -> None:
    host = _make_editing_host(editing=False)
    host._edit_buffer = "hello"
    host.clear_edit_buffer()
    assert host._edit_buffer == "hello"

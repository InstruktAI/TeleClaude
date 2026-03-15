"""Characterization tests for teleclaude.cli.tui.views.preparation_actions."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin

# --- PreparationViewActionsMixin._next_command (static method) ---


@pytest.mark.unit
def test_next_command_appends_slug_when_provided() -> None:
    result = PreparationViewActionsMixin._next_command("next-build", "my-slug")
    assert result == "/next-build my-slug"


@pytest.mark.unit
def test_next_command_returns_base_only_when_no_slug() -> None:
    result = PreparationViewActionsMixin._next_command("next-build", None)
    assert result == "/next-build"


@pytest.mark.unit
def test_next_command_prefixes_with_slash() -> None:
    result = PreparationViewActionsMixin._next_command("prepare", "feat-x")
    assert result.startswith("/")

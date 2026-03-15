"""Characterization tests for teleclaude.cli.tui.widgets.group_separator."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.group_separator import GroupSeparator


@pytest.mark.unit
def test_group_separator_is_importable() -> None:
    assert GroupSeparator is not None


@pytest.mark.unit
def test_group_separator_default_connector_col_is_two() -> None:
    sep = GroupSeparator()
    assert sep._connector_col == 2


@pytest.mark.unit
def test_group_separator_accepts_custom_connector_col() -> None:
    sep = GroupSeparator(connector_col=5)
    assert sep._connector_col == 5

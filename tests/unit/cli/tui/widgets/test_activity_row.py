"""Characterization tests for teleclaude.cli.tui.widgets.activity_row.

ActivityRow is a Textual Widget subclass. Its render() method assembles a
Rich Text from reactive attributes. The class can be instantiated without a
running app; reactive attributes are readable on the instance.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.activity_row import ActivityRow


@pytest.mark.unit
def test_activity_row_is_importable() -> None:
    assert ActivityRow is not None


@pytest.mark.unit
def test_activity_row_default_attributes_are_empty_strings() -> None:
    row = ActivityRow()
    assert row.title == ""
    assert row.subtitle == ""
    assert row.status_text == ""
    assert row.timestamp == ""

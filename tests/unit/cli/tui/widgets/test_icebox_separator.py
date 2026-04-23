"""Characterization tests for teleclaude.cli.tui.widgets.icebox_separator."""

from __future__ import annotations

import pytest
from textual.geometry import Size

from teleclaude.cli.tui.widgets.icebox_separator import IceboxSeparator


@pytest.mark.unit
def test_icebox_separator_is_importable() -> None:
    assert IceboxSeparator is not None


@pytest.mark.unit
def test_icebox_separator_default_line_width() -> None:
    sep = IceboxSeparator(line_width=40)
    assert sep._line_width == 40


@pytest.mark.unit
def test_icebox_separator_renders_natural_width_without_size_constraint() -> None:
    """Without a pane size constraint, renders at the full natural line width."""
    sep = IceboxSeparator(line_width=11)
    rendered = sep.render()
    # "  " (2) + "├" (1) + "─" * 11 = 14 chars
    assert len(rendered.plain) == 14


@pytest.mark.unit
def test_icebox_separator_render_fits_narrow_pane() -> None:
    """Separator must not overflow past the content area when the pane is narrow."""
    sep = IceboxSeparator(line_width=11)
    sep._size = Size(12, 1)  # outer=12; padding: 0 1 → content_area=10
    rendered = sep.render()
    content_area = 12 - 2  # CSS padding: 0 1 = 2 horz chars
    assert len(rendered.plain) <= content_area

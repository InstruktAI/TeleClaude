"""Characterization tests for teleclaude.cli.tui.widgets.trashed_separator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.text import Text
from textual.geometry import Size

from teleclaude.cli.tui.widgets.trashed_separator import TrashedSeparator


@pytest.mark.unit
def test_trashed_separator_renders_branch_line(snapshot: object) -> None:
    """TrashedSeparator must render a branch connector (├─) in CONNECTOR_COLOR."""
    # Fixed line_width for snapshot stability
    sep = TrashedSeparator(line_width=20)
    # Mock size for consistent layout
    with patch.object(TrashedSeparator, "outer_size", Size(80, 1)):
        rendered = sep.render()
    assert isinstance(rendered, Text)
    # The snapshot covers both the characters and the color style
    assert rendered == snapshot

"""Characterization tests for teleclaude.cli.tui.views.config.

ConfigView is a full Textual widget subclass. All pure editing and rendering
logic is already characterized in test_config_editing.py and test_config_render.py.
This file covers module-level imports and class availability.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_config_view_is_importable() -> None:
    from teleclaude.cli.tui.views.config import ConfigView

    assert ConfigView is not None

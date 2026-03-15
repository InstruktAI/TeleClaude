"""Characterization tests for teleclaude.cli.tui.views.config_render.

ConfigContentRenderMixin methods all depend on Textual widget state (active_subtab,
adapter sections, people data, etc.) and call self.refresh(). They cannot be
exercised without a mounted Textual app. This file verifies the class is importable
and will catch renames or removed classes.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_config_content_render_mixin_is_importable() -> None:
    from teleclaude.cli.tui.views.config_render import ConfigContentRenderMixin

    assert ConfigContentRenderMixin is not None

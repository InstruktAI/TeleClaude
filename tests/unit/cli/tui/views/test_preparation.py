"""Characterization tests for teleclaude.cli.tui.views.preparation.

PreparationView is a full Textual widget. Action logic is characterized in
test_preparation_actions.py. This file verifies the class is importable.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_preparation_view_is_importable() -> None:
    from teleclaude.cli.tui.views.preparation import PreparationView

    assert PreparationView is not None

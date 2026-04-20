"""Characterization tests for teleclaude.cli.tui.views.jobs.

JobsView is a full Textual widget with no standalone pure functions beyond
what is covered by widget dependencies. This file verifies the class is importable.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.views.jobs import JobsView


@pytest.mark.unit
def test_jobs_view_is_importable() -> None:
    assert JobsView is not None

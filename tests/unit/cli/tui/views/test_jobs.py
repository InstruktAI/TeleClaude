"""Characterization tests for teleclaude.cli.tui.views.jobs.

JobsView is a full Textual widget with no standalone pure functions beyond
what is covered by widget dependencies. This file verifies the class is importable.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from teleclaude.api_models import JobDTO
from teleclaude.cli.tui.views.jobs import JobsView


@pytest.mark.unit
def test_jobs_view_is_importable() -> None:
    assert JobsView is not None


@pytest.mark.unit
def test_jobs_view_skips_rebuild_when_jobs_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    view = JobsView()
    rebuild = Mock()
    monkeypatch.setattr(view, "_rebuild", rebuild)
    job = JobDTO(name="daily", type="agent", status="never")

    view.update_data([job])
    view.update_data([JobDTO(name="daily", type="agent", status="never")])
    view.update_data([job.model_copy(update={"status": "running"})])

    assert rebuild.call_count == 2

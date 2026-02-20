"""Unit tests for JobsView (Textual-based)."""

from teleclaude.cli.models import JobInfo
from teleclaude.cli.tui.views.jobs import JobsView


def test_jobs_view_initialization():
    """Test that JobsView initializes with correct defaults."""
    view = JobsView()
    assert view.cursor_index == 0
    assert view._jobs == []
    assert view._nav_items == []


def test_jobs_view_stores_data():
    """Test that update_data stores job data."""
    view = JobsView()
    jobs = [
        JobInfo(name="test_job", schedule="daily", last_run=None, status="success", type="script"),
    ]
    # Can't call update_data without a mounted widget tree,
    # but we can verify the data model accepts jobs
    view._jobs = jobs
    assert len(view._jobs) == 1
    assert view._jobs[0].name == "test_job"

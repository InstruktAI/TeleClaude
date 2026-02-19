"""Unit tests for JobsView."""

import curses
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.cli.models import JobInfo, SessionInfo
from teleclaude.cli.tui.views.jobs import JobsView


@pytest.fixture
def mock_api():
    return AsyncMock()


@pytest.fixture
def jobs_view(mock_api):
    return JobsView(api=mock_api)


@pytest.mark.asyncio
async def test_jobs_view_initialization(jobs_view):
    """Test that JobsView initializes with correct defaults."""
    assert jobs_view.selected_index == 0
    assert jobs_view.scroll_offset == 0
    assert jobs_view.flat_items == []


@pytest.mark.asyncio
async def test_jobs_view_refresh(jobs_view):
    """Test refreshing view with jobs and sessions."""
    jobs = [
        JobInfo(name="test_job", schedule="daily", last_run=None, status="success", type="script"),
    ]
    sessions = [
        SessionInfo(
            session_id="sess1",
            active_agent="claude",
            status="active",
            title="Job Run",
            session_metadata={"job_name": "test_job"},
            created_at="2024-01-01T00:00:00Z",
        ),
        SessionInfo(
            session_id="sess2",
            active_agent="claude",
            status="active",
            title="Regular Session",
            created_at="2024-01-01T00:00:00Z",
        ),  # Normal session, should be filtered
    ]

    await jobs_view.refresh(jobs, sessions)

    assert len(jobs_view.flat_items) > 0
    # Should contain header "Active Runs", the active session, spacer, header "Job Catalog", and the job
    assert "Active Runs" in jobs_view.flat_items
    assert sessions[0] in jobs_view.flat_items
    assert sessions[1] not in jobs_view.flat_items
    assert "Job Catalog" in jobs_view.flat_items
    assert jobs[0] in jobs_view.flat_items


@pytest.mark.asyncio
async def test_jobs_view_navigation(jobs_view):
    """Test navigation skips headers/spacers."""
    jobs = [
        JobInfo(name="job1", schedule="daily", last_run=None, status="success", type="script"),
        JobInfo(name="job2", schedule="daily", last_run=None, status="success", type="script"),
    ]
    sessions = [
        SessionInfo(
            session_id="sess1",
            active_agent="claude",
            status="active",
            title="Job Run",
            session_metadata={"job_name": "job1"},
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    await jobs_view.refresh(jobs, sessions)

    # Structure:
    # 0: "Active Runs"
    # 1: Session(sess1)
    # 2: "" (spacer)
    # 3: "Job Catalog"
    # 4: Job(job1)
    # 5: Job(job2)

    # Initial selection should adjust to first selectable item (Session 1 at index 1)
    assert jobs_view.selected_index == 1
    assert isinstance(jobs_view.flat_items[jobs_view.selected_index], SessionInfo)

    # Move down -> spacer -> catalog header -> Job 1 (index 4)
    jobs_view.move_down()
    assert jobs_view.selected_index == 4
    assert isinstance(jobs_view.flat_items[jobs_view.selected_index], JobInfo)
    assert jobs_view.flat_items[jobs_view.selected_index].name == "job1"

    # Move down -> Job 2 (index 5)
    jobs_view.move_down()
    assert jobs_view.selected_index == 5
    assert jobs_view.flat_items[jobs_view.selected_index].name == "job2"

    # Move up -> Job 1 (index 4)
    jobs_view.move_up()
    assert jobs_view.selected_index == 4

    # Move up -> catalog header -> spacer -> Session 1 (index 1)
    jobs_view.move_up()
    assert jobs_view.selected_index == 1

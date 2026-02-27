"""Unit tests for role-based tool filtering."""

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, ROLE_WORKER
from teleclaude.core.tool_access import filter_tool_names


def test_filter_member():
    tools = ["telec agents status", "telec sessions start"]
    filtered = filter_tool_names(None, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "telec agents status" not in filtered
    assert "telec sessions start" in filtered


def test_filter_admin():
    tools = ["telec agents status"]
    filtered = filter_tool_names(None, tools, human_role=HUMAN_ROLE_ADMIN)
    assert "telec agents status" in filtered


def test_filter_unauthorized():
    tools = ["telec sessions start", "telec docs get"]
    filtered = filter_tool_names(None, tools, human_role=None)
    assert "telec sessions start" not in filtered
    assert "telec docs get" in filtered


def test_filter_worker_and_member():
    # Worker role should filter worker tools, Member role should filter member tools.
    # Union of exclusions.
    tools = ["telec todo work", "telec agents status", "telec docs get"]
    filtered = filter_tool_names(ROLE_WORKER, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "telec todo work" not in filtered  # Excluded by worker
    assert "telec agents status" not in filtered  # Excluded by member
    assert "telec docs get" in filtered

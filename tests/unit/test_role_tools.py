"""Unit tests for role-based tool filtering."""

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, ROLE_WORKER
from teleclaude.core.tool_access import WORKER_ALLOWED_TOOLS, filter_tool_names, is_tool_allowed


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
    # Worker whitelist + member exclusions both apply.
    tools = ["telec todo work", "telec agents status", "telec sessions send"]
    filtered = filter_tool_names(ROLE_WORKER, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "telec todo work" not in filtered  # Not in worker whitelist
    assert "telec agents status" not in filtered  # Not in worker whitelist
    assert "telec sessions send" in filtered  # In worker whitelist


def test_worker_whitelist_allows_send():
    """Worker can send messages (the original bug)."""
    assert is_tool_allowed(ROLE_WORKER, "telec sessions send")


def test_worker_whitelist_blocks_spawn():
    """Worker cannot spawn new sessions."""
    assert not is_tool_allowed(ROLE_WORKER, "telec sessions start")
    assert not is_tool_allowed(ROLE_WORKER, "telec sessions run")


def test_worker_whitelist_blocks_orchestration():
    """Worker cannot use orchestrator commands."""
    assert not is_tool_allowed(ROLE_WORKER, "telec todo work")
    assert not is_tool_allowed(ROLE_WORKER, "telec todo prepare")
    assert not is_tool_allowed(ROLE_WORKER, "telec todo mark-phase")


def test_worker_whitelist_blocks_unknown_tools():
    """New clearance-gated tools are denied by default for workers."""
    assert not is_tool_allowed(ROLE_WORKER, "telec some-future-tool")


def test_worker_allowed_tools_complete():
    """Sanity check: all whitelisted tools are actually allowed."""
    for tool in WORKER_ALLOWED_TOOLS:
        assert is_tool_allowed(ROLE_WORKER, tool), f"{tool} should be allowed for workers"

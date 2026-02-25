"""Unit tests for role-based tool filtering."""

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, ROLE_WORKER
from teleclaude.core.tool_access import filter_tool_names


def test_filter_member():
    tools = ["teleclaude__deploy", "teleclaude__start_session"]
    filtered = filter_tool_names(None, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "teleclaude__deploy" not in filtered
    assert "teleclaude__start_session" in filtered


def test_filter_admin():
    tools = ["teleclaude__deploy"]
    filtered = filter_tool_names(None, tools, human_role=HUMAN_ROLE_ADMIN)
    assert "teleclaude__deploy" in filtered


def test_filter_unauthorized():
    tools = ["teleclaude__start_session", "teleclaude__get_context"]
    filtered = filter_tool_names(None, tools, human_role=None)
    assert "teleclaude__start_session" not in filtered
    assert "teleclaude__get_context" in filtered


def test_filter_worker_and_member():
    # Worker role should filter worker tools, Member role should filter member tools.
    # Union of exclusions.
    tools = ["teleclaude__next_work", "teleclaude__deploy", "teleclaude__get_context"]
    filtered = filter_tool_names(ROLE_WORKER, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "teleclaude__next_work" not in filtered  # Excluded by worker
    assert "teleclaude__deploy" not in filtered  # Excluded by member
    assert "teleclaude__get_context" in filtered

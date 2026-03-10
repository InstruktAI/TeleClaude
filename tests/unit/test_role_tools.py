"""Unit tests for role-based tool filtering."""

from teleclaude.cli.telec import is_command_allowed
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, ROLE_INTEGRATOR, ROLE_WORKER
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
    assert "telec docs get" not in filtered


def test_filter_worker_and_member():
    # Worker system role + member human role: orchestrator-only commands denied.
    tools = ["telec todo work", "telec agents status", "telec sessions send"]
    filtered = filter_tool_names(ROLE_WORKER, tools, human_role=HUMAN_ROLE_MEMBER)
    assert "telec todo work" not in filtered  # orchestrator-only
    assert "telec agents status" not in filtered  # orchestrator-only
    assert "telec sessions send" in filtered  # allowed for worker


def test_command_auth_worker_restricted():
    """Worker is blocked from orchestrator-only commands."""
    assert not is_command_allowed("sessions start", ROLE_WORKER, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("sessions run", ROLE_WORKER, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("todo work", ROLE_WORKER, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("todo prepare", ROLE_WORKER, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("todo mark-phase", ROLE_WORKER, HUMAN_ROLE_MEMBER)


def test_command_auth_integrator_restricted():
    """Integrator is blocked from commands not on its whitelist."""
    assert not is_command_allowed("sessions run", ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("sessions send", ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("todo work", ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
    assert not is_command_allowed("channels publish", ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)

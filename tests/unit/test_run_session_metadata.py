"""Unit tests for server-side session metadata derivation in run_session()."""

from __future__ import annotations

from teleclaude.api_server import COMMAND_ROLE_MAP


def test_run_session_derives_worker_metadata():
    """/next-build command maps to worker/builder."""
    role_info = COMMAND_ROLE_MAP.get("next-build")
    assert role_info is not None
    system_role, job = role_info
    assert system_role == "worker"
    assert job == "builder"


def test_run_session_derives_integrator_metadata():
    """/next-integrate command maps to integrator/integrator."""
    role_info = COMMAND_ROLE_MAP.get("next-integrate")
    assert role_info is not None
    system_role, job = role_info
    assert system_role == "integrator"
    assert job == "integrator"


def test_run_session_unknown_command_no_metadata():
    """Unrecognized command produces no metadata."""
    role_info = COMMAND_ROLE_MAP.get("unknown-command")
    assert role_info is None


def test_command_role_map_worker_commands():
    """All worker lifecycle commands map to worker system_role."""
    worker_cmds = [
        "next-build", "next-bugs-fix", "next-review-build", "next-review-plan",
        "next-review-requirements", "next-fix-review", "next-finalize",
        "next-prepare-discovery", "next-prepare-draft", "next-prepare-gate",
    ]
    for cmd in worker_cmds:
        role_info = COMMAND_ROLE_MAP.get(cmd)
        assert role_info is not None, f"{cmd} missing from COMMAND_ROLE_MAP"
        assert role_info[0] == "worker", f"{cmd} should map to worker, got {role_info[0]}"


def test_command_role_map_orchestrator_commands():
    """Orchestrator commands map to orchestrator system_role."""
    orch_cmds = ["next-prepare", "next-work"]
    for cmd in orch_cmds:
        role_info = COMMAND_ROLE_MAP.get(cmd)
        assert role_info is not None, f"{cmd} missing from COMMAND_ROLE_MAP"
        assert role_info[0] == "orchestrator", f"{cmd} should map to orchestrator, got {role_info[0]}"

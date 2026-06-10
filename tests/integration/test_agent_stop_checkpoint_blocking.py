"""Functional coverage for agent stop checkpoint behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli.telec.handlers import code
from teleclaude.constants import CHECKPOINT_MESSAGE
from teleclaude.core.agents import AgentName
from teleclaude.git import Repo
from teleclaude.hooks.checkpoint import get_checkpoint_content, run_heuristics
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.hooks.checkpoint_flags import (
    has_authored_main_commit_flag,
    record_integrator_maintenance_marker,
)
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

_SPEC = "project/spec/feature/integration/agent-stop-checkpoint-blocking"

# Named constants for instruction identity checks — shared with production code
# (sourced from constants.py FileCategory instruction strings).
_TELEC_SYNC_INSTR = "Run `telec sync`"


def _init_supported_repo(repo_path: Path) -> Repo:
    repo_path.mkdir(parents=True)
    repo = Repo.init(repo_path)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Checkpoint Test")
    repo.git.config("user.email", "checkpoint-test@example.test")
    (repo_path / "teleclaude" / "hooks" / "checkpoint").mkdir(parents=True)
    (repo_path / "teleclaude" / "hooks" / "checkpoint" / "__init__.py").write_text("", encoding="utf-8")
    (repo_path / "agents" / "commands").mkdir(parents=True)
    (repo_path / "agents" / "commands" / "next-work.md").write_text("# Next Work\n", encoding="utf-8")
    (repo_path / "teleclaude" / "core").mkdir(parents=True)
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# initial\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    return repo


def _empty_timeline() -> TurnTimeline:
    return TurnTimeline(tool_calls=[], has_data=True)


def _timeline_with_bash(command: str) -> TurnTimeline:
    record = ToolCallRecord(tool_name="bash", input_data={"command": command})
    return TurnTimeline(tool_calls=[record], has_data=True)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_main_branch_review_gate_follows_authored_commit_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "checkpoint-author-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)

    first_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# authored\n", encoding="utf-8")
    code._commit_under_lock(
        message="test: authored main commit",
        includes=["teleclaude/core/tracked.py"],
        project_root=repo_path,
        system_role=None,
    )

    marker_after_commit = has_authored_main_commit_flag(session_id)
    authored_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=first_anchor_sha,
    )
    marker_after_first_checkpoint = has_authored_main_commit_flag(session_id)
    second_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=first_anchor_sha,
    )

    peer_anchor_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "teleclaude" / "core" / "tracked.py").write_text("# peer\n", encoding="utf-8")
    repo.git.commit("-am", "peer commit")
    peer_payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CODEX,
        project_path=str(repo_path),
        turn_anchor_sha=peer_anchor_sha,
    )

    assert marker_after_commit is True
    assert marker_after_first_checkpoint is False
    assert second_payload is None
    assert peer_payload is None
    assert {"authored_payload": authored_payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_doc_only_main_commit_does_not_arm_review_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "checkpoint-docs-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)

    (repo_path / "docs").mkdir(parents=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    code._commit_under_lock(
        message="docs: add guide",
        includes=["docs/guide.md"],
        project_root=repo_path,
        system_role=None,
    )

    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP5A")
def test_directory_pathspec_does_not_arm_review_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit whose actual files are all docs does not arm review, even when
    the requested pathspec contained a directory token like 'docs'."""
    session_id = "checkpoint-dir-pathspec-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    monkeypatch.setattr(code, "get_session_id", lambda: session_id)

    (repo_path / "docs").mkdir(parents=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "docs: seed guide")
    (repo_path / "docs" / "guide.md").write_text("# Guide\n\nUpdated\n", encoding="utf-8")

    # The user passes the directory 'docs' as a declared include. The gate must
    # resolve the actual committed file list and not treat the directory token as
    # code.
    code._commit_under_lock(
        message="docs: update guide",
        includes=["docs"],
        project_root=repo_path,
        system_role=None,
    )

    assert has_authored_main_commit_flag(session_id) is False


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_integrator_maintenance_force_fires_on_merge_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    session_id = "integrator-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = repo.git.rev_parse("HEAD").strip()

    # Simulate a delivery that touched daemon code, deps, setup, and docs
    (repo_path / "teleclaude" / "core" / "service.py").write_text("# service\n", encoding="utf-8")
    (repo_path / "pyproject.toml").write_text("[project]\nname='tc'\n", encoding="utf-8")
    (repo_path / "teleclaude" / "project_setup").mkdir(parents=True, exist_ok=True)
    (repo_path / "teleclaude" / "project_setup" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "chore: delivery squash")

    post_merge_sha = repo.git.rev_parse("HEAD").strip()
    record_integrator_maintenance_marker(session_id, f"{pre_merge_sha}..{post_merge_sha}")

    # Force-fire path: integrator role, marker present, no turn-local Edit/Write
    anchor_sha = pre_merge_sha
    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=anchor_sha,
        system_role="integrator",
    )

    assert payload is not None
    # No review, commit reminder, or test/log noise (NotIn is not a string-literal violation)
    assert "review gate" not in payload
    assert "telec code commit" not in payload
    assert "Run targeted tests" not in payload
    assert "instrukt-ai-logs" not in payload
    assert {"maintenance_payload": payload} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_integrator_maintenance_diff_failure_returns_visible_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "integrator-invalid-range-session"
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))
    record_integrator_maintenance_marker(session_id, "missing-before..missing-after")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=None,
        system_role="integrator",
    )

    assert payload == CHECKPOINT_MESSAGE


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_non_integrator_session_no_maintenance_force_fire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "worker-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    anchor_sha = repo.git.rev_parse("HEAD").strip()

    # No marker, non-integrator role, main advanced by someone else
    repo.git.commit("--allow-empty", "-m", "chore: remote advance")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=anchor_sha,
        system_role="worker",
    )

    # No maintenance force-fire for non-integrator without marker
    assert payload is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP11")
def test_agents_merge_delta_does_not_surface_restart_self_in_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agents/** in a merge delta must NOT surface restart-self in the maintenance
    path — that is a non-main_only action and the integrator's responsibility is
    maintenance (setup/deps/restart/sync), not artifact reload."""
    session_id = "integrator-agents-session"
    repo_path = tmp_path / "repo"
    repo = _init_supported_repo(repo_path)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = repo.git.rev_parse("HEAD").strip()
    (repo_path / "agents" / "commands" / "next-deploy.md").write_text("# Deploy\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "feat: add deploy command")
    post_merge_sha = repo.git.rev_parse("HEAD").strip()
    record_integrator_maintenance_marker(session_id, f"{pre_merge_sha}..{post_merge_sha}")

    payload = get_checkpoint_content(
        session_id=session_id,
        transcript_path=None,
        agent_name=AgentName.CLAUDE,
        project_path=str(repo_path),
        turn_anchor_sha=pre_merge_sha,
        system_role="integrator",
    )

    # Agents-only merge delta has no main_only categories → no maintenance payload
    # (telec sync is main_only, so it would surface for docs; agents/** matches
    # telec sync too, so a payload could surface — but restart-self must not appear)
    if payload is not None:
        assert "restart self" not in payload
        assert "telec sessions restart" not in payload


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_docs_dir_change_surfaces_telec_sync(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["docs/spec.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions
    assert {"docs_sync_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_docs_dir_telec_sync_suppressed_with_evidence(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))
    timeline = _timeline_with_bash(_TELEC_SYNC_INSTR)

    result = run_heuristics(["docs/spec.md"], timeline, context)

    assert _TELEC_SYNC_INSTR not in result.required_actions


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP10")
def test_agent_command_change_surfaces_both_restart_and_telec_sync(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["agents/commands/next-build.md"], _empty_timeline(), context)

    assert _TELEC_SYNC_INSTR in result.required_actions
    assert {"agent_cmd_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP9")
def test_bare_md_outside_docs_stays_no_action(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["README.md"], _empty_timeline(), context)

    # Bare .md is no-action only: no category instructions
    assert result.required_actions == []
    assert result.categories == []


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_make_install_surfaces_for_makefile_change(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["Makefile"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"makefile_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_make_install_surfaces_for_install_dir_change(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["teleclaude/install/script.sh"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"install_dir_result": result.required_actions} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CP4")
def test_pyproject_toml_routes_to_uv_sync_not_make_install(
    tmp_path: Path,
    snapshot: object,
) -> None:
    repo_path = tmp_path / "repo"
    _init_supported_repo(repo_path)
    context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path=str(repo_path))

    result = run_heuristics(["pyproject.toml"], _empty_timeline(), context)

    assert result.required_actions != []
    assert {"pyproject_result": result.required_actions} == snapshot
